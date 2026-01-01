# SPDX-FileCopyrightText: 2023-present Gene Wood <gene_wood@cementhorizon.com>
#
# SPDX-License-Identifier: GPL-3.0-or-later
import collections.abc
import copy
import json
import os
import pickle
import textwrap
from typing import Any, Dict, Hashable, Set
import botocore.exceptions
import boto3
import boto3.dynamodb.types

PERMISSION_MESSAGE = textwrap.dedent("""\
    The AWS Lambda function's IAM role is missing a necessary permission. The
    role requires the following permissions:
    dynamodb:{CreateTable,TagResource,PutItem,DescribeTable,GetItem}
    and should have a policy like :
    {
        "Sid": "AllowPersistentMap",
        "Effect": "Allow",
        "Action": [
            "dynamodb:CreateTable",
            "dynamodb:TagResource",
            "dynamodb:PutItem",
            "dynamodb:DescribeTable",
            "dynamodb:GetItem"
        ],
        "Resource": "arn:aws:dynamodb:*:*:table/AWSLambdaPersistence"
    }""")


def _check_for_mixed_args(kwargs: Dict, config_keys: Set) -> None:
    """Validate the arguments passed into PersistentMap

    Check the arguments passed into PersistentMap to determine if there is a
    mix of configuration settings and map key value pairs. If there are, raise
    an exception to prevent this ambiguous state.

    :param kwargs: The dictionary of arguments passed when the PersistentMap
                   is instantiated
    :param config_keys: The configuration arguments PersistentMap takes
    :return: None
    """
    config_arguments = kwargs.keys() & config_keys
    map_arguments = kwargs.keys() - config_keys
    if (not kwargs or (config_arguments and not map_arguments) or
            (map_arguments and not config_arguments)):
        return
    example_config_args = ", ".join([f"{x}='{kwargs[x]}'"
                                     for x in config_arguments])
    example_map_args = {x: kwargs[x] for x in map_arguments}.__repr__()
    example_env_vars = " ".join([f'PERSISTENCE_{x.upper()}="{kwargs[x]}"'
                                 for x in config_arguments])
    raise MixOfConfigAndMapArgsPassed(
        "A mix of PersistentMap configuration arguments and map arguments "
        "were passed when the PersistentMap was instantiated, which isn't "
        "allowed.\nPersistentMap configuration arguments "
        f"{', '.join(config_arguments)} were passed and map arguments "
        f"{', '.join(map_arguments)} were passed.\nPlease either set "
        f"PersistentMap configuration with environment variables (e.g. export "
        f"{example_env_vars})\nor initialize the content of the PersistentMap "
        f"by calling the update method :\nexample = "
        f"PersistentMap({example_config_args})\n"
        f"example.update({example_map_args})")


class MixOfConfigAndMapArgsPassed(Exception):
    pass


class MissingAWSIAMPermissions(Exception):
    pass


class PersistentMap(collections.abc.MutableMapping):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Create a new PersistentMap

        Create a new PersistentMap, a dictionary-like variable that persists
        its contents into an AWS DynamoDB table to enable AWS Lambda functions
        to maintain state between invocations.

        :param args: Either a mapping of contents for the new PersistentMap or
            an iterable of tuples with the new content
        :param kwargs: A dict of keyword arguments. These should either be
            PersistentMap configuration settings or the contents of the new
            PersistentMap, but not both.
        """
        self._total_puts = 0
        self._total_gets = 0
        self._store = dict()
        self._previous_store = None
        self.save_on_set = True
        config_keys = {
            'table_name',
            'table_key',
            'key_field_name',
            'value_field_name',
        }
        self.table_name = 'AWSLambdaPersistence'
        self.table_key = os.getenv('AWS_LAMBDA_FUNCTION_NAME')
        self.key_field_name = 'key'
        self.value_field_name = 'value'

        _check_for_mixed_args(kwargs, config_keys)
        # Prefer environment variables over the values passed as arguments,
        # and finally use the defaults if neither were set
        for name in config_keys:
            value = os.getenv(
                f"PERSISTENCE_{name.upper()}",
                kwargs[name] if name in kwargs else None)
            if value is not None:
                setattr(self, name, value)
            if name in kwargs:
                del kwargs[name]

        if args or kwargs:
            self.save_on_set = False
            self.update(dict(*args, **kwargs))
            self.save_on_set = True
            self.__save_store()
        else:
            try:
                self._store = self.__fetch_store()
            except botocore.exceptions.ClientError as e:
                if e.response['Error']['Code'] == 'AccessDeniedException':
                    raise MissingAWSIAMPermissions(PERMISSION_MESSAGE)
                else:
                    raise
            self._previous_store = copy.deepcopy(self._store)

    def __create_table(self) -> None:
        """Create a new DynamoDB table

        Create a new DynamoDB table, wait for it to be provisioned, then
        write an empty mapping into a record.

        :return: None
        """
        client = boto3.client('dynamodb')
        dynamodb = boto3.resource('dynamodb')
        client.create_table(
            AttributeDefinitions=[{
                'AttributeName': self.key_field_name,
                'AttributeType': 'S'
            }],
            TableName=self.table_name,
            KeySchema=[{
                'AttributeName': self.key_field_name,
                'KeyType': 'HASH'
            }],
            BillingMode='PROVISIONED',
            ProvisionedThroughput={
                'ReadCapacityUnits': 1,
                'WriteCapacityUnits': 1
            },
            Tags=[{
                'Key': 'Description',
                'Value': f'This table contains persistent data for the AWS '
                         f'Lambda function {self.table_name} added by '
                         f'aws_lambda_persistence'
            }]
        )
        # It can take up to 15 seconds for table creation to complete
        client.get_waiter('table_exists').wait(
            TableName=self.table_name, WaiterConfig={'Delay': 2})
        table = dynamodb.Table(self.table_name)
        table.load()
        self._total_puts += 1
        table.put_item(
            Item={self.key_field_name: self.table_key,
                  self.value_field_name: pickle.dumps({})}
        )

    def __fetch_store(self) -> Dict:
        """Fetch and return the PersistentMap stored in DynamoDB

        Try to read the existing PersistentMap from DynamoDB. If it's
        missing, create a new empty record. If not, fetch the contents,
        deserialized them and return them.

        :return: A dict of the contents of the PersistentMap stored in DynamoDB
        """
        dynamodb = boto3.resource('dynamodb')
        table = dynamodb.Table(self.table_name)
        table_missing = False
        try:
            table.load()
        except dynamodb.meta.client.exceptions.ResourceNotFoundException:
            table_missing = True

        if table_missing:
            self.__create_table()
            return {}
        else:
            self._total_gets += 1
            response = table.get_item(
                Key={self.key_field_name: self.table_key},
                ProjectionExpression='#v',
                ExpressionAttributeNames={'#v': self.value_field_name}
            )
            serialized_value = response.get('Item', {}).get(
                self.value_field_name)
            if serialized_value is None:
                return {}
            else:
                # https://github.com/boto/boto3/issues/846#issuecomment-504472076
                return pickle.loads(serialized_value.value)

    def __save_store(self) -> None:
        """Write the _store dict into DynamoDB

        Serialize _store, write it to DynamoDB and update _previous_store with
        the contents of _store

        :return: None
        """
        if (pickle.dumps(self._store) != pickle.dumps(self._previous_store) and
                self.save_on_set):
            dynamodb = boto3.resource('dynamodb')
            try:
                table = dynamodb.Table(self.table_name)
                self._total_puts += 1
                table.put_item(
                    Item={self.key_field_name: self.table_key,
                          self.value_field_name: pickle.dumps(self._store)}
                )
            except dynamodb.meta.client.exceptions.ClientError as e:
                if e.response['Error']['Code'] == 'AccessDeniedException':
                    raise MissingAWSIAMPermissions(PERMISSION_MESSAGE)
                else:
                    raise
            self._previous_store = copy.deepcopy(self._store)

    def __setitem__(self, key: Hashable, value: Any) -> None:
        if (key not in self._store or
                pickle.dumps(value) != pickle.dumps(self._store[key])):
            self._store.__setitem__(key, value)
            self.__save_store()

    def __delitem__(self, key: Hashable) -> None:
        self._store.__delitem__(key)
        self.__save_store()

    def __getitem__(self, key: Hashable) -> Any:
        return self._store.__getitem__(key)

    def __iter__(self):
        return self._store.__iter__()

    def __len__(self):
        return self._store.__len__()

    def __repr__(self):
        return self._store.__repr__()

    def clear(self) -> None:
        self.save_on_set = False
        self._store.clear()
        self.save_on_set = True
        self.__save_store()

    def update(self, other=(), /, **kwargs):
        self.save_on_set = False
        self._store.update(other, **kwargs)
        self.save_on_set = True
        self.__save_store()


def lambda_handler(event, context):
    import traceback
    try:
        test_aws_lambda_persistence()
    except Exception as e:
        print('Exception caught')
        print(traceback.format_exc())
        print(e)
    return {
        'statusCode': 200,
        'body': json.dumps('Success')
    }


def test_aws_lambda_persistence():
    import time
    from datetime import datetime
    client = boto3.client('dynamodb')
    table_name = 'TestingAWSLambdaPersistence'
    table_key = os.getenv('AWS_LAMBDA_FUNCTION_NAME')
    key_field_name = 'key'
    dynamodb = boto3.resource('dynamodb')
    table = dynamodb.Table(table_name)
    try:
        client.describe_table(TableName=table_name)
        print(f'Deleting current table {table_name}')
        client.delete_table(TableName=table_name)
        waiter = client.get_waiter('table_not_exists')
        waiter.wait(TableName=table_name, WaiterConfig={'Delay': 2})
    except client.exceptions.ResourceNotFoundException:
        pass

    os.environ["PERSISTENCE_TABLE_NAME"] = table_name
    os.environ["PERSISTENCE_TABLE_KEY"] = table_key
    start = time.time()
    data = PersistentMap()
    end = time.time()
    print(f"Time to create new DynamoDB table : {end - start}")
    assert data._total_gets == 0
    assert data._total_puts == 1

    del data
    start = time.time()
    data = PersistentMap(foo=42)
    end = time.time()
    print(f"Time to create new PersistentMap : {end - start}")
    assert data._total_gets == 0
    assert data._total_puts == 1
    assert data['foo'] == 42

    del data
    start = time.time()
    data = PersistentMap()
    end = time.time()
    print(f"Time to load new PersistentMap : {end - start}")
    assert data._total_gets == 1
    assert data._total_puts == 0
    assert data['foo'] == 42

    start = time.time()
    data['foo'] = 52
    end = time.time()
    print(f"Time to change a value : {end - start}")
    assert data._total_gets == 1
    assert data._total_puts == 1
    assert data['foo'] == 52

    start = time.time()
    data.update({'foo': 62, 'bar': 'buz'})
    end = time.time()
    print(f"Time to update with kwargs : {end - start}")
    assert data._total_gets == 1
    assert data._total_puts == 2
    assert data['foo'] == 62
    assert data['bar'] == 'buz'

    start = time.time()
    del data['bar']
    end = time.time()
    print(f"Time to del a key : {end - start}")
    assert data._total_gets == 1
    assert data._total_puts == 3
    assert 'bar' not in data

    start = time.time()
    data.clear()
    end = time.time()
    print(f"Time to clear : {end - start}")
    assert data._total_gets == 1
    assert data._total_puts == 4
    assert len(data) == 0

    del data
    data = PersistentMap()
    data['foo'] = 42
    assert data['foo'] == 42
    current_datetime = datetime.now()
    print("Storing datetime")
    data['bar'] = current_datetime

    del data
    data = PersistentMap()
    print("Fetching datetime")
    assert data['bar'] == current_datetime

    table.delete_item(
        Key={key_field_name: table_key}
    )

    del data
    print("Reading from an existing table but a missing key")
    data = PersistentMap()

    print("Setting specific values")
    data.update({
        'bar': datetime(2021, 11, 13, 3, 16, 8, 549614),
        'foo': {'buz': 'bad'}
    })
    assert data._total_puts == 1
    data.update({
        'bar': datetime(2021, 11, 13, 3, 16, 8, 549614),
        'foo': {'buz': 'bad'}
    })
    print("Setting the same values which should not trigger a put")
    assert data._total_puts == 1

    # print(f"Trigger mixed argument exception")
    # data = PersistentMap(table_key='test', foo='bar', baz=1)
