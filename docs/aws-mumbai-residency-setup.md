# AWS Mumbai residency proof

This setup creates one encrypted, private S3 bucket in AWS Mumbai and one narrowly
scoped GitHub OIDC role. CI uploads, reads, and deletes 32 bytes of synthetic data,
then records AWS-authenticated bucket-region metadata. No long-lived AWS key is stored.

## One-time setup

1. Create an AWS Free Plan account.
2. Open AWS CloudShell in the **Asia Pacific (Mumbai) / `ap-south-1`** region.
3. From a checkout of this repository, run:

   ```bash
   aws cloudformation deploy \
     --region ap-south-1 \
     --stack-name production-engineering-os-residency \
     --template-file infra/aws-residency-proof/cloudformation.yml \
     --capabilities CAPABILITY_IAM
   ```

4. Read the two outputs:

   ```bash
   aws cloudformation describe-stacks \
     --region ap-south-1 \
     --stack-name production-engineering-os-residency \
     --query 'Stacks[0].Outputs' \
     --output table
   ```

5. In GitHub, create the `india-residency` environment. Add the output values as
   environment variables named `AWS_RESIDENCY_BUCKET` and `AWS_RESIDENCY_ROLE_ARN`.

The template intentionally fails outside `ap-south-1`. Public access is blocked,
server-side encryption is enabled, abandoned probe objects expire after one day, and
the role can access only the synthetic `residency-probes/` prefix.
