# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.0.0] - 2026-01-01

### Added

- Initial code for AWS Lambda Persistence which is a Python module that enables AWS Lambda functions to
  maintain state and persist data between invocations by writing to a dict-like 
  variable. It achieves this by using the DynamoDB free tier and so it can be used
  without adding any costs to your project.

[unreleased]: https://github.com/gene1wood/aws-lambda-persistence/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/gene1wood/aws-lambda-persistence/releases/tag/v1.0.0
