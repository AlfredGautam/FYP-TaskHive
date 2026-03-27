from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0010_notification"),
    ]

    operations = [
        migrations.CreateModel(
            name="EmailVerificationOTP",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=120)),
                ("email", models.EmailField(db_index=True, max_length=254)),
                ("password_hash", models.CharField(max_length=128)),
                ("otp_hash", models.CharField(max_length=128)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("expires_at", models.DateTimeField()),
                ("used", models.BooleanField(default=False)),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
        migrations.AddIndex(
            model_name="emailverificationotp",
            index=models.Index(fields=["email", "used", "-created_at"], name="core_emailve_email_0cf518_idx"),
        ),
    ]
