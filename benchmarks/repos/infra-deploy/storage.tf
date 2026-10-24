resource "aws_s3_bucket" "backups" {
  bucket = "customer-backups"
}

resource "aws_s3_bucket_acl" "backups" {
  bucket = aws_s3_bucket.backups.id
  acl    = "public-read"
}
