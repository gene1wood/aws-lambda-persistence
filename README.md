# AWS Lambda Persistence

AWS Lambda Persistence is a Python module that enables AWS Lambda functions to
maintain state and persist data between invocations by writing to a dict-like 
variable. It achieves this by using the DynamoDB free tier and so it can be used
without adding any costs to your project.

[![PyPI - Version](https://img.shields.io/pypi/v/aws-lambda-persistence.svg)](https://pypi.org/project/aws-lambda-persistence)
[![PyPI - Python Version](https://img.shields.io/pypi/pyversions/aws-lambda-persistence.svg)](https://pypi.org/project/aws-lambda-persistence)

-----

**Table of Contents**

* [Example](#example)
* [How to install it](#how-to-install-it)
  * [Reference a public AWS Lambda Layer](#reference-a-public-aws-lambda-layer)
  * [Include the package in your function zip](#include-the-package-in-your-function-zip)
  * [Install the package as an AWS Lambda Layer](#install-the-package-as-an-aws-lambda-layer)
* [Permissions needed](#permissions-needed)
* [How to use it](#how-to-use-it)
  * [Avoiding reserved words](#avoiding-reserved-words)
  * [Configuring the PersistentMap](#configuring-the-persistentmap)
* [Why use DynamoDB for the data store?](#why-use-dynamodb-for-the-data-store-)
* [Questions for which this is a solution](#questions-for-which-this-is-a-solution)
* [License](#license)

## Example

Here's an example of an AWS Lambda function that depends on information that
comes from some expensive, time-consuming operation but it only needs to produce
new data every four hours. For every other AWS Lambda invocation, it should just
use whatever the most recent data is.

This example uses the built-in AWS Lambda cache, and backs it with PersistentMap
for when the cache is lost.

```python
import datetime
from aws_lambda_persistence import PersistentMap
def lambda_handler(event, context):
    global data
    if 'data' not in globals():
        # data isn't present in Lambda cache already
        data = PersistentMap()
    if 'expiration_datetime' in data:
        if data['expiration_datetime'] < datetime.datetime.now():
            data.update({
                'special_value': expensive_function(event),
                'expiration_datetime': datetime.datetime.now() + datetime.timedelta(hours=4)
            })
```

And here's an entire CloudFormation template example

```yaml
AWSTemplateFormatVersion: '2010-09-09'
Resources:
  ExampleFunction:
    Type: AWS::Lambda::Function
    Properties:
      Code:
        ZipFile: |
          import datetime
          from aws_lambda_persistence import PersistentMap
          def lambda_handler(event, context):
              global data
              if 'data' not in globals():
                  data = PersistentMap()
                  result = ("The persistent data wasn't in the Lambda cache so "
                           "it was pulled from DynamoDB. ")
              else:
                  result = "The persistent data was pulled from Lambda cache. "
              if 'last_run' in data:
                  result += f"This function was last run at {data['last_run']}"
              else:
                  result += f"This is the first time the function has run."
              data['last_run'] = datetime.datetime.now()
              return(result)
      Handler: index.lambda_handler
      Layers:
        - arn:aws:lambda:us-west-2:220481034027:layer:aws-lambda-persistence:2
      PackageType: Zip
      Role: !GetAtt ExampleRole.Arn
      Runtime: python3.14
      # On first run, if the DynamoDB doesn't exist, execution can take 11+ seconds
      # Clod starts with a pull from DynamoDB can take 4+ seconds
      Timeout: 30  
  ExampleRole:
    Type: AWS::IAM::Role
    Properties:
      AssumeRolePolicyDocument:
        Version: '2012-10-17'
        Statement:
        - Effect: Allow
          Principal:
            Service:
            - lambda.amazonaws.com
          Action:
          - sts:AssumeRole
      Policies:
      - PolicyName: AllowPersistentMap
        PolicyDocument:
          Version: '2012-10-17'
          Statement:
          - Effect: Allow
            Action:
            - dynamodb:CreateTable
            - dynamodb:TagResource
            - dynamodb:PutItem
            - dynamodb:DescribeTable
            - dynamodb:GetItem
            Resource: arn:aws:dynamodb:*:*:table/AWSLambdaPersistence
```

## How to install it

You can use AWS Lambda Persistence a few different ways

* Reference a public hosted AWS Lambda Layer containing the package
* Include the package in your AWS Lambda function zip
* Install the package as an AWS Lambda Layer in your AWS account
* Copy and paste the package contents into your AWS Lambda function

### Reference a public AWS Lambda Layer

The current version of the AWS Lambda Persistence module is hosted in this AWS Lambda Layer

`arn:aws:lambda:us-west-2:220481034027:layer:aws-lambda-persistence:2`

By referencing this layer in your AWS Lambda function, the module is available for use with a line like

`from aws_lambda_persistence import PersistentMap`

Note : If, later there is a bugfix or feature addition, and this README is updated to reflect a new AWS Lambda Layer
version, you'll need to update your AWS Function to use the new ARN with the new version number, otherwise you'll
continue to be using the original/older version.

### Include the package in your function zip

You can include the `aws_lambda_persistence` directory in your AWS Lambda function's zip file. It has no dependencies
(which aren't natively present in all AWS Lambda Python runtimes).

### Install the package as an AWS Lambda Layer

If you don't want to reference the public layer as described above, you can deploy it as a layer in your own account

## Permissions needed

Your AWS Lambda function that uses AWS Lambda Persistence will need the
following permissions on the AWSLambdaPersistence DynamoDB

* `dynamodb:CreateTable`
* `dynamodb:TagResource`
* `dynamodb:PutItem`
* `dynamodb:DescribeTable`
* `dynamodb:GetItem`

You can grant your AWS Lambda function these rights by adding this policy to the
function's IAM Role

```
{
    "Version": "2012-10-17",
    "Statement": [
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
        }
    ]
}
```

## How to use it

The recommended way to use the persistent map is to create a global variable
that is a PersistentMap. This will allow AWS Lambda to first try to fetch the
data from the AWS cache before you fall back to pulling from the PersistentMap.
First try to retrieve the data from the AWS Lambda cache. This can be done by
looking for the variable in the global scope. If it is present, just use the
existing variable (which will already be a PersistentMap). If it's missing,
create a new empty variable using PersistentMap with a line like 
`data = PersistentMap`.

```python
import datetime
from aws_lambda_persistence import PersistentMap
def lambda_handler(event, context):
    global data
    if 'data' not in globals():
        # data isn't present in Lambda cache already
        data = PersistentMap()
```

Once this is done, if there was any existing state stored in the variable from
a previous invocation of the AWS Lambda function, that state is now loaded
into the variable in this runtime. You can read from it as you would any map.

```python
    if 'example' in data:
        print(data['example'])
```

In this example we first check to see if the key is present in the map because
if this is the first time the AWS Lambda function has ever been run, the map
would be empty.

Any modifications you make to the variable are immediately persisted into
DynamoDB.

```python
    data['example'] = datetime.datetime.now()
```

Since any change is immediately persisted, you may want to batch up changes
to avoid overly inefficient use of DynamoDB. For example, if you want to set
multiple keys in the variable, don't set them one after the other, instead use
the `update()` method of the map to update them all at one time

```python
    date.update({
        'example': datetime.datetime.now(),
        'foo': datetime.datetime.now() + datetime.timedelta(hours=4)
    })
```

You can also update the contents of the map when you instantiate the variable.
This is true for any map (like a dict).

```python
import datetime
from aws_lambda_persistence import PersistentMap
def lambda_handler(event, context):
    global data
    if 'data' not in globals():
        # data isn't present in Lambda cache already
        data = PersistentMap({
            'example': datetime.datetime.now()
        })
```

You should only use a single PersistentMap in a given AWS Lambda function
because each instantiation of a PersistentMap within an AWS Lambda function
is referring to the same map. This shouldn't be an issue though as you can
store as many keys as you wish within the PersistentMap. This behavior can
be overridden if needed with the `table_key` setting described below.

### Avoiding reserved words

The only limitation with updating data in the map during instantiation is that
you have to make sure to avoid the 4 reserved words for keys which are used to
configure the PersistentMap. Those 4 reserved words are

* `table_name`
* `table_key`
* `key_field_name`
* `value_field_name`

If you need to use any keys in your variable with these reserved names, just
avoid setting them during instantiation, like this

```python
from aws_lambda_persistence import PersistentMap
def lambda_handler(event, context):
    global bad_example
    if 'bad_example' not in globals():
        # If you happen to want to set your own data called "table_name"
        # don't do it like this because you'll be accidentally configuring
        # the PersistentMap 
        bad_example = PersistentMap({
            'table_name': 'foo'
        })
```

and instead set them *after* the variable is already created, like this

```python
from aws_lambda_persistence import PersistentMap
def lambda_handler(event, context):
    global data
    if 'data' not in globals():
        # data isn't present in Lambda cache already
        data = PersistentMap()
    data['table_name'] = 'foo'
```

More about why these reserved words exist can be found below in the
[section on configuring the PersistentMap](#configuring-the-persistentmap)

### Configuring the PersistentMap

There are 4 configuration settings that override the default way that the
PersistentMap works. These defaults can be overridden either with environment
variables or with arguments passed into PersistentMap when the variable is
instantiated. The default values shouldn't need to be overridden, but they can
be if you have a need.

The 4 configuration settings are

* `table_name` : This is the name of the DynamoDB table to persist data into.
  The default for this is `AWSLambdaPersistence`. In most cases you won't need
  to override this default, because any number of different AWS Lambda
  functions can all store their PersistentMap all in this single default
  DynamoDB table without collision.
* `table_key` : This is the unique key in the DynamoDB table to store the
  PersistentMap in. By default, this is set to the name of the AWS Lambda
  function so that each different AWS Lambda function gets its own
  PersistentMap to prevent name collision between different lambda
  functions that have PersistentMap keys with the same name.
* `key_field_name`: This is the name of the key field in the key value pair in
  DynamoDB which stores the PersistentMap data. The default value for this is
  the name `key`. You shouldn't need to change this.
* `value_field_name`: This is the name of the value field in the key value pair
  in DynamoDB which stores the PersistentMap data. The default value for this
  is the name `value`. You shouldn't need to change this.  

To set these configuration settings when you instantiate the PersistentMap,
pass them in as arguments

```python
from aws_lambda_persistence import PersistentMap
def lambda_handler(event, context):
    global data
    if 'data' not in globals():
        # data isn't present in Lambda cache already
        data = PersistentMap(table_key='my special table key')
    data['example'] = 'foo'
```

To set these configuration settings using environment variables, prefix the
setting name with `PERSISTENCE_` and use upper case letters.

As an example, you would set, in your [AWS Lambda function environment
variables](https://docs.aws.amazon.com/lambda/latest/dg/configuration-envvars.html),
an environment variable called `PERSISTENCE_TABLE_KEY` with a value  like 
`my special table key`

Note : Avoid setting a configuration value with *both* an environment variable
and an argument at instantiation as it could be confusing. If you do set a setting
both in an environment variable and as an argument at instantiation, the
PersistentMap will use the environment variable value.

## Namespace and Security

AWS Lambda Persistence stores all data in a single DynamoDB table. Each Lambda
function reads and writes to a single dedicated row in the table. By default,
the key for the row is the name of the lambda function. This creates a separate
namespace for each lambda function that uses AWS Lambda Persistence.

There is however no security control that prevents Lambda function A from interacting
with the persistence map for Lambda function B. Lambda function A could change
the AWS_LAMBDA_FUNCTION_NAME environment variable and change values in Lambda function
B's record.

## How to build the `layer.zip` file

```shell
# Create the `layer.zip` file with the `aws_lambda_persistence/__init__.py` file 
zip build/layer.zip aws_lambda_persistence/__init__.py
# Move the file under a new `python` directory in the zip file
printf "@ aws_lambda_persistence/__init__.py\n@=python/aws_lambda_persistence/__init__.py\n" | zipnote -w build/layer.zip
```

## Why use DynamoDB for the data store?

Other AWS storage systems aren't free or are only free for the first 12 months

* S3
* RDS
* DocumentDB
* Keyspaces
* Memcached or Redis via ElastiCache
* EFS
* EBS

Other AWS systems not designed to store data could potentially be used instead

* SSM Parameter Store
* EC2 Security Groups

## What's next?

* Change how data is stored in DynamoDB to use more than one key value pair for a data structure
  because there's a 400KB size limit. We could look for unusually large values inside the data
  structure and break those out into additional key value pairs, or just restructure how things
  are stored so every value in the data structure gets it's own key value pair and 400KB limit.

## Questions for which this is a solution

* https://stackoverflow.com/questions/48630799/best-practice-to-store-single-value-in-aws-lambda
* https://stackoverflow.com/questions/58398218/how-to-keep-state-in-aws-lambdas
* https://stackoverflow.com/questions/54807110/aws-lambda-store-state-of-a-queue
* https://stackoverflow.com/questions/38535988/simple-global-state-for-lambda-functions
* https://stackoverflow.com/questions/49267830/maintain-session-state-in-aws-lambda
* https://stackoverflow.com/questions/58659839/how-to-determine-outside-state-of-a-variable-using-aws-lambda
* https://stackoverflow.com/questions/41668376/aws-lambda-serverless-website-session-maintaining
* https://stackoverflow.com/questions/65212754/aws-lambda-where-to-store-temporary-secret-data
* https://stackoverflow.com/questions/50212300/how-would-i-create-a-global-counter-for-aws-lambda-functions
* https://www.reddit.com/r/aws/

## License

`aws-lambda-persistence` is distributed under the terms of the [GPL-3.0-or-later](https://spdx.org/licenses/GPL-3.0-or-later.html) license.
