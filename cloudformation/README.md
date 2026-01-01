These CloudFormation templates are used to deploy and test the public layer. Users of the AWS-Lambda-Persistence tool
don't need to use any of these templates.

* `aws_lambda_persistence_layer.yaml` : CloudFormation template that deploys the AWS Lambda Persistence Layer. This
  only needs to be run once in the 220481034027 AWS account. There's no need for users of the AWS Lambda Persistence
  Layer to deploy this template.
* `aws_lambda_persistence_sam_layer.yaml` : CloudFormation template that deploys the AWS Lambda Persistence Layer using
  SAM. This only needs to be run once in the 220481034027 AWS account. There's no need for users of the AWS Lambda
  Persistence Layer to deploy this template.
* `test_aws_lambda_persistence_layer.yaml` : CloudFormation template that deploys an AWS Lambda function which uses the
  AWS Lambda Persistence Layer and runs the built-in tests to determine if the layer is working correctly. This template
  creates an IAM Role that grants both the permissions needed to use AWS Lambda Persistence Layer as well as two
  additional permissions that are used in the testing, the `dynamodb:DeleteTable` and `dynamodb:DeleteItem` permissions
  on the `TestingAWSLambdaPersistence` DynamoDB table. After deploying the stack, the test can be run by going to the
  new Lambda function called `aws-lambda-persistence-layer-tester` and running a Lambda test, passing it an input event
  of any kind (e.g. the Hello World event). If the tests pass Lambda will show a `statusCode` response of 200. If not,
  an exception will be returned.