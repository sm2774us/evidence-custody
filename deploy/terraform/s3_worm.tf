# S3 Object Lock (COMPLIANCE) evidence bucket + separate audit-anchor bucket.
# COMPLIANCE mode: no principal, including root, can shorten retention or delete a locked version.
variable "name_prefix" { type = string }
variable "retention_days" {
  type    = number
  default = 2555
}

resource "aws_kms_key" "evidence" {
  description             = "${var.name_prefix} evidence encryption"
  enable_key_rotation     = true
  deletion_window_in_days = 30
}

resource "aws_s3_bucket" "evidence" {
  bucket              = "${var.name_prefix}-evidence"
  object_lock_enabled = true
}

resource "aws_s3_bucket_versioning" "evidence" {
  bucket = aws_s3_bucket.evidence.id
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket_object_lock_configuration" "evidence" {
  bucket = aws_s3_bucket.evidence.id
  rule {
    default_retention {
      mode = "COMPLIANCE"
      days = var.retention_days
    }
  }
  depends_on = [aws_s3_bucket_versioning.evidence]
}

resource "aws_s3_bucket_server_side_encryption_configuration" "evidence" {
  bucket = aws_s3_bucket.evidence.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.evidence.arn
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_public_access_block" "evidence" {
  bucket                  = aws_s3_bucket.evidence.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

data "aws_iam_policy_document" "tls_only" {
  statement {
    sid       = "DenyInsecureTransport"
    effect    = "Deny"
    actions   = ["s3:*"]
    resources = [aws_s3_bucket.evidence.arn, "${aws_s3_bucket.evidence.arn}/*"]
    principals {
      type        = "*"
      identifiers = ["*"]
    }
    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_s3_bucket_policy" "evidence" {
  bucket = aws_s3_bucket.evidence.id
  policy = data.aws_iam_policy_document.tls_only.json
}

# Independent anchor for signed audit checkpoints (different account/owner in production).
resource "aws_s3_bucket" "anchors" {
  bucket              = "${var.name_prefix}-audit-anchors"
  object_lock_enabled = true
}
resource "aws_s3_bucket_versioning" "anchors" {
  bucket = aws_s3_bucket.anchors.id
  versioning_configuration { status = "Enabled" }
}
resource "aws_s3_bucket_object_lock_configuration" "anchors" {
  bucket = aws_s3_bucket.anchors.id
  rule {
    default_retention {
      mode = "COMPLIANCE"
      days = var.retention_days
    }
  }
  depends_on = [aws_s3_bucket_versioning.anchors]
}
