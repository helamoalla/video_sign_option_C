# VideoSign — Geo-Adaptive Accessible Video Processing

VideoSign is an asynchronous video-accessibility platform developed for Cyrkil. It processes uploaded media and generates:

- Speech transcription
- Multilingual translations
- WebVTT subtitles
- Sign-language avatar videos
- Subtitle and avatar video compositions
- A protected multilingual web player
- Geo-adaptive sign-language routing

> This repository currently uses CWASA, ALSL and Dicta-Sign resources for prototype development only. They are blocked in production until Cyrkil-owned or commercially licensed avatar assets replace them.

---

## Architecture

The application runs with Docker Compose and contains:

- **FastAPI**: API, authentication, job management and artifact access
- **PostgreSQL**: jobs, credentials, ownership and retention metadata
- **Redis**: Celery broker and result backend
- **Celery worker**: asynchronous video processing
- **Celery Beat**: scheduled media-retention cleanup
- **FFmpeg/ffprobe**: validation, sanitisation and encoding
- **Playwright/CWASA**: prototype sign-avatar rendering
- **Whisper**: speech transcription
- **Groq**: translation and gloss generation
- **MoviePy**: subtitle/avatar composition

---

## Main features

- Authenticated API access
- Per-user and per-tenant job isolation
- Asynchronous processing with persisted job state
- Upload size and media validation
- FFprobe-based stream inspection
- Media metadata sanitisation
- Per-user job quotas
- Idempotent submissions
- Automatic retries for temporary failures
- Dead-letter state after retry exhaustion
- Cooperative job cancellation
- Private generated artifacts
- Signed playback URLs
- Automatic upload cleanup
- Output-retention expiration
- Audited user-requested deletion
- Hourly scheduled cleanup
- Sign-asset bundle readiness checks
- Prototype/production licence enforcement
- GitHub Actions CI
- Reproducible locked dependencies

---

## Project structure

```text
video_sign/
├── app/
│   ├── avatar/
│   ├── pipelines/
│   ├── director/
│   ├── tools/
│   ├── assets/fonts/
│   ├── main.py
│   ├── auth.py
│   ├── models.py
│   ├── tasks.py
│   ├── celery_app.py
│   ├── job_submission.py
│   ├── job_control.py
│   ├── job_quotas.py
│   ├── media_validation.py
│   ├── media_retention.py
│   ├── asset_readiness.py
│   └── asset_license.py
├── data/
│   └── sign_languages/
├── docs/
├── licenses/
├── external/
│   └── alsl_avatar/
├── test/
├── outputs/
├── uploads/
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── requirements.lock.txt
├── pytest.ini
├── THIRD_PARTY_NOTICES.md
└── README.md
```

---

## Requirements

Install:

- Docker Desktop
- Docker Compose
- Git

Docker Desktop must be running before starting the project.

---

## Clone the repository

```bash
git clone https://github.com/helamoalla/video_sign_option_C.git
cd video_sign_option_C
```

---

## Environment configuration

Copy the example environment file:

### PowerShell

```powershell
Copy-Item .env.example .env
```

Configure at least the following values in `.env`:

```env
POSTGRES_DB=videosign
POSTGRES_USER=videosign
POSTGRES_PASSWORD=replace-with-a-secure-password

DATABASE_URL=postgresql+psycopg2://videosign:replace-with-a-secure-password@postgres:5432/videosign

CELERY_BROKER_URL=redis://redis:6379/0
CELERY_RESULT_BACKEND=redis://redis:6379/1

INTERNAL_BASE_URL=http://videosign:8000
PUBLIC_BASE_URL=http://localhost:8000

GROQ_API_KEY=replace-with-your-groq-key
MAGIC_HOUR_API_KEY=replace-if-director-is-used

API_KEY_PEPPER=replace-with-at-least-32-random-characters
INTERNAL_WORKER_TOKEN=replace-with-at-least-32-random-characters
PLAYBACK_SIGNING_SECRET=replace-with-at-least-32-random-characters

PLAYBACK_TOKEN_SECONDS=600

MAX_REQUEST_BYTES=110100480
MAX_UPLOAD_BYTES=104857600

MAX_MEDIA_DURATION_SECONDS=600
MAX_VIDEO_WIDTH=3840
MAX_VIDEO_HEIGHT=2160
MAX_VIDEO_PIXELS=8294400

MAX_ACTIVE_JOBS_PER_USER=2
DEVELOPMENT_DAILY_JOB_LIMIT=20
STANDARD_DAILY_JOB_LIMIT=100
ENTERPRISE_DAILY_JOB_LIMIT=1000

OUTPUT_RETENTION_HOURS=168
FAILED_MEDIA_RETENTION_HOURS=24
RETENTION_CLEANUP_BATCH_SIZE=100

APP_ENV=development
ALLOW_RESEARCH_ASSETS=true
```

Never commit `.env`, API keys, database passwords or signing secrets.

Generate secure secrets with:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Run it separately for:

- `API_KEY_PEPPER`
- `INTERNAL_WORKER_TOKEN`
- `PLAYBACK_SIGNING_SECRET`

---

## Prototype and production asset policy

For local development:

```env
APP_ENV=development
ALLOW_RESEARCH_ASSETS=true
```

This allows the prototype CWASA provider.

For production:

```env
APP_ENV=production
ALLOW_RESEARCH_ASSETS=false
```

Production rejects `cwasa_multilang` and `cwasa_arabic`.

Production must use Cyrkil-owned or commercially licensed avatar videos. The planned provider is `licensed_video`, which is not implemented yet.

See:

- `docs/DATA_SOURCES.md`
- `THIRD_PARTY_NOTICES.md`
- `data/sign_languages/asset_provenance.json`

---

## Build and start

```powershell
docker compose up -d --build
```

Check the services:

```powershell
docker compose ps
```

Expected services:

- `videosign-api`
- `videosign-worker`
- `videosign-postgres`
- `videosign-redis`
- `videosign-beat`

Follow logs:

```powershell
docker compose logs -f videosign worker beat
```

Open Swagger:

```text
http://localhost:8000/docs
```

---

## Health and readiness

Basic health:

```powershell
curl.exe http://localhost:8000/health
```

Expected:

```json
{
  "status": "healthy"
}
```

Sign-asset readiness:

```powershell
curl.exe http://localhost:8000/ready
```

A ready response returns HTTP 200 and:

```json
{
  "status": "ready",
  "code": "SIGN_ASSETS_READY",
  "problems": []
}
```

`/ready` returns HTTP 503 if the pinned sign-asset counts or checksum do not match.

---

## Database creation

For a new database, application startup currently creates missing SQLAlchemy tables automatically.

This is temporary. Production should use Alembic migrations instead of `Base.metadata.create_all()`.

Inspect the jobs table:

```powershell
docker compose exec postgres psql -U videosign -d videosign -c "\d video_jobs"
```

Inspect API credentials:

```powershell
docker compose exec postgres psql -U videosign -d videosign -c "\d api_credentials"
```

Inspect deletion audits:

```powershell
docker compose exec postgres psql -U videosign -d videosign -c "\d media_deletion_audits"
```

---

## API authentication

Protected endpoints require:

```http
X-API-Key: <raw-api-key>
```

Only the HMAC-SHA256 hash of an API key is stored in PostgreSQL. The raw key is displayed once during creation.

`X-Internal-Worker-Token` is reserved for internal worker-to-API requests. It is not a user credential.

---

## Generate an API key

Generate user and tenant UUIDs:

```powershell
python -c "import uuid; print('USER_ID=' + str(uuid.uuid4())); print('TENANT_ID=' + str(uuid.uuid4()))"
```

Create the credential using one PowerShell line:

```powershell
docker compose exec videosign python -m app.create_api_key --user-id "USER_UUID" --tenant-id "TENANT_UUID" --role developer --plan development --expires-days 90
```

Example:

```powershell
docker compose exec videosign python -m app.create_api_key --user-id "3d6e1254..." --tenant-id "127b0825-..." --role developer --plan development --expires-days 90
```

Copy the displayed API key immediately. It cannot be retrieved later.

For local PowerShell tests:

```powershell
$API_KEY = "cyrkil_dev_replace_with_generated_key"
```

In a future frontend, users should receive credentials through a controlled account/onboarding flow. End users should not run the database CLI themselves.

---

## Submit a video-processing job

Endpoint:

```http
POST /process-video-assets
```

Supported extensions include:

```text
.mp4 .mov .avi .mkv .webm .mp3 .wav .m4a .aac .ogg
```

PowerShell example:

```powershell
curl.exe -X POST "http://localhost:8000/process-video-assets" `
  -H "X-API-Key: $API_KEY" `
  -F "video=@C:\path\to\video.mp4" `
  -F "languages=french,arabic,english" `
  -F "sign_languages=lsf,lsa,bsl" `
  -F "manual_text=hello" `
  -F "avatar_provider_name=cwasa_multilang"
```

Expected HTTP status:

```text
202 Accepted
```

Example response:

```json
{
  "job_id": "28f3af74-2ffd-4ef0-909e-f99bb5870550",
  "status": "queued",
  "status_url": "/jobs/28f3af74-2ffd-4ef0-909e-f99bb5870550",
  "idempotency_key": "a71bf639-b3cb-44f2-9fa4-68b4a23326a0",
  "idempotent_replay": false
}
```

---

## Idempotency

The client may provide:

```http
Idempotency-Key: <stable-key>
```

Example:

```powershell
$IDEMPOTENCY_KEY = [guid]::NewGuid().ToString()

curl.exe -X POST "http://localhost:8000/process-video-assets" `
  -H "X-API-Key: $API_KEY" `
  -H "Idempotency-Key: $IDEMPOTENCY_KEY" `
  -F "video=@C:\path\to\video.mp4" `
  -F "languages=french" `
  -F "sign_languages=lsf" `
  -F "manual_text=hello" `
  -F "avatar_provider_name=cwasa_multilang"
```

Rules:

- Same user, key and request: return the existing job.
- Same key with different content or parameters: reject the request.
- Missing key: the backend generates one automatically.
- A future frontend should generate one key for each intentional submission and reuse it when retrying that submission.

The request fingerprint also protects against accidental duplicate active submissions.

---

## Check job status

```powershell
$JOB_ID = "replace-with-job-id"
```

```powershell
curl.exe "http://localhost:8000/jobs/$JOB_ID" `
  -H "X-API-Key: $API_KEY"
```

Possible statuses:

- `queued`
- `processing`
- `retrying`
- `completed`
- `failed`
- `cancelled`

The response also includes:

- `stage`
- `progress`
- `result`
- `error`
- `media_available`
- `media_expires_at`
- `media_deleted_at`

Jobs are isolated by `user_id` and `tenant_id`. Another user receives `404 Job not found`.

---

## Open the generated video player

When a job is completed and its media is available, `GET /jobs/{job_id}` generates:

```json
{
  "result": {
    "player_url": "http://localhost:8000/outputs/.../player.html?token=...",
    "playback_expires_at": "...",
    "iframe": "<iframe ...></iframe>"
  }
}
```

Copy `result.player_url` and open it directly in a browser.

The signed playback token:

- Is restricted to one job
- Has a short expiration
- Cannot outlive media retention
- Allows the player to load its manifest, subtitles and videos

Never store an old playback URL permanently. Request the job again to generate a fresh URL.

---

## Download a private artifact

Endpoint:

```http
GET /outputs/{job_id}/{artifact_path}
```

Example:

```powershell
curl.exe `
  "http://localhost:8000/outputs/$JOB_ID/subtitles/french.vtt" `
  -H "X-API-Key: $API_KEY" `
  --output french.vtt
```

Example rendered video:

```powershell
curl.exe `
  "http://localhost:8000/outputs/$JOB_ID/rendered/french_lsf.mp4" `
  -H "X-API-Key: $API_KEY" `
  --output french_lsf.mp4
```

Unauthorized and missing artifacts both return `404` to prevent information disclosure.

Path traversal and symbolic-link escapes are rejected.

---

## Cancel a job

Endpoint:

```http
POST /jobs/{job_id}/cancel
```

```powershell
curl.exe -X POST `
  "http://localhost:8000/jobs/$JOB_ID/cancel" `
  -H "X-API-Key: $API_KEY"
```

Behaviour:

- Queued/retrying tasks are revoked safely.
- Processing tasks stop cooperatively at the next cancellation checkpoint.
- A cancelled job cannot later become completed.
- Partial uploads and generated outputs are removed.
- Terminal jobs that cannot be cancelled return HTTP 409.

Confirm:

```powershell
curl.exe "http://localhost:8000/jobs/$JOB_ID" `
  -H "X-API-Key: $API_KEY"
```

Expected final status:

```json
{
  "status": "cancelled",
  "stage": "cancelled"
}
```

---

## Delete generated media

Endpoint:

```http
DELETE /jobs/{job_id}/media
```

Use the job UUID—not the player URL:

```powershell
curl.exe -X DELETE `
  "http://localhost:8000/jobs/$JOB_ID/media" `
  -H "X-API-Key: $API_KEY"
```

Example response:

```json
{
  "job_id": "...",
  "media_available": false,
  "media_deleted_at": "...",
  "audit_id": "...",
  "upload_deleted": false,
  "output_deleted": true
}
```

Job metadata remains in PostgreSQL for auditing, but the media can no longer be downloaded or played.

Active-job deletion returns HTTP 409.

---

## Media retention

Completed outputs are retained according to:

```env
OUTPUT_RETENTION_HOURS=168
```

Failed-job derivatives use:

```env
FAILED_MEDIA_RETENTION_HOURS=24
```

Celery Beat submits an hourly cleanup task:

```text
app.tasks.cleanup_expired_media
```

The worker performs the deletion and creates records in `media_deletion_audits`.

Check the Beat schedule:

```powershell
docker compose exec beat python -c "from app.celery_app import celery_app; print(celery_app.conf.beat_schedule)"
```

Inspect cleanup logs:

```powershell
docker compose logs worker | Select-String "cleanup_expired_media"
```

Inspect deletion audits:

```powershell
docker compose exec postgres psql -U videosign -d videosign -c "SELECT job_id, reason, requested_by, upload_deleted, output_deleted, created_at FROM media_deletion_audits ORDER BY created_at DESC LIMIT 10;"
```

---

## Retries and dead-letter state

Temporary failures are retried automatically with exponential delays:

```text
30 seconds → 60 seconds → 120 seconds
```

The delay is capped at five minutes.

Validation errors, missing assets and unsupported languages are not retried.

Jobs track:

- `attempt_count`
- `max_attempts`
- `last_error_code`
- `retry_requested_at`
- `dead_lettered_at`

After retry exhaustion, the job is marked failed with:

```text
stage = dead_lettered
```

Inspect:

```powershell
docker compose exec postgres psql -U videosign -d videosign -c "SELECT id, status, stage, attempt_count, max_attempts, last_error_code, dead_lettered_at FROM video_jobs ORDER BY created_at DESC LIMIT 10;"
```

---

## Queue recovery test

Stop the worker:

```powershell
docker compose stop worker
```

Submit a valid job. It should remain `queued`.

Confirm Redis contains the queued task:

```powershell
docker compose exec redis redis-cli LLEN celery
```

Restart the worker:

```powershell
docker compose start worker
```

Follow processing:

```powershell
docker compose logs -f worker
```

The same persisted job should complete without creating another job.

---

## Sign-language capability check

Endpoint:

```http
GET /avatar/capabilities/{provider_name}/{language}
```

Example:

```powershell
curl.exe "http://localhost:8000/avatar/capabilities/cwasa_multilang/lsf"
```

Example response:

```json
{
  "provider": "cwasa_multilang",
  "language": "lsf",
  "supported": true,
  "asset_count": 1003
}
```

---

## Asset readiness

The application verifies:

- The pinned bundle version
- Expected SiGML counts per language
- The canonical bundle checksum

Run:

```powershell
docker compose exec videosign python -m app.asset_readiness
```

Expected:

```json
{
  "ready": true,
  "code": "SIGN_ASSETS_READY",
  "problems": []
}
```

---

## Licence and provenance verification

Run:

```powershell
docker compose exec videosign python -m pytest -q `
  /app/test/test_asset_provenance.py `
  /app/test/test_asset_license.py `
  /app/test/test_asset_license_policy.py
```

Expected policy:

| Asset | Production decision |
|---|---|
| `cwasa_multilang` | Denied |
| `cwasa_arabic` | Denied |
| `ibm_plex_arabic` | Allowed |

Verify development access:

```powershell
docker compose exec `
  -e APP_ENV=development `
  -e ALLOW_RESEARCH_ASSETS=true `
  videosign python -c "from app.avatar.provider_factory import get_avatar_provider; print(type(get_avatar_provider('cwasa_multilang')).__name__)"
```

Expected:

```text
CwasaMultilangProvider
```

Verify production blocking:

```powershell
docker compose exec `
  -e APP_ENV=production `
  -e ALLOW_RESEARCH_ASSETS=false `
  videosign python -c "from app.avatar.provider_factory import get_avatar_provider; get_avatar_provider('cwasa_multilang')"
```

Expected:

```text
ProviderNotApprovedForProductionError
```

This exception means the production protection works correctly.

---

## Testing

Run non-integration tests:

```powershell
docker compose exec videosign python -m pytest -q -m "not integration"
```

Run the complete test suite:

```powershell
docker compose exec videosign python -m pytest -q /app/test
```

Run media-validation integration tests:

```powershell
docker compose exec videosign python -m pytest -q /app/test/test_media_validation.py
```

Run specific areas:

```powershell
docker compose exec videosign python -m pytest -q /app/test/test_authorization.py
docker compose exec videosign python -m pytest -q /app/test/test_job_cancellation.py
docker compose exec videosign python -m pytest -q /app/test/test_media_retention.py
docker compose exec videosign python -m pytest -q /app/test/test_asset_provenance.py
```

Tests marked `integration` require external tools such as FFmpeg and ffprobe.

---

## Continuous integration

GitHub Actions runs:

1. Python 3.11.15
2. Locked dependency installation
3. `pip check`
4. Non-integration tests
5. Docker image build
6. Docker dependency comparison with `requirements.lock.txt`

Workflow:

```text
.github/workflows/ci.yml
```

---

## Useful Docker commands

Rebuild after code changes:

```powershell
docker compose up -d --build
```

Restart without rebuilding:

```powershell
docker compose restart videosign worker beat
```

Check services:

```powershell
docker compose ps
```

API logs:

```powershell
docker compose logs --tail=100 videosign
```

Worker logs:

```powershell
docker compose logs --tail=100 worker
```

Beat logs:

```powershell
docker compose logs --tail=100 beat
```

Worker connectivity:

```powershell
docker compose exec worker celery -A app.celery_app inspect ping
```

Redis queue length:

```powershell
docker compose exec redis redis-cli LLEN celery
```

---

## Development file-copy shortcut

For quick local testing, a changed Python file can be copied without rebuilding:

```powershell
docker compose cp .\app\main.py videosign:/app/app/main.py
docker compose restart videosign
```

For worker code:

```powershell
docker compose cp .\app\tasks.py worker:/app/app/tasks.py
docker compose restart worker
```

Manual copies are temporary. They disappear when a container is recreated. Always rebuild before final testing or deployment.

---

## Security notes

- Never expose `API_KEY_PEPPER`.
- Never give users `INTERNAL_WORKER_TOKEN`.
- Never place raw API keys in Git.
- Raw user API keys are displayed only once.
- Generated artifacts are private by default.
- Job ownership is enforced using user and tenant IDs.
- Playback URLs contain short-lived signed tokens.
- Upload filenames are replaced with server-generated paths.
- Uploaded media is validated and sanitised.
- Path traversal is rejected.
- User-requested deletions are audited.
- Production must use HTTPS and secure secret management.

---

## Current limitations

- CWASA, ALSL and Dicta-Sign assets are prototype-only.
- The production `licensed_video` provider is not implemented yet.
- Commercial rights for current prototype assets are not confirmed.
- Sign-language vocabulary coverage remains limited.
- Generated gloss quality requires native signer validation.
- Database schema creation still uses `create_all()` instead of Alembic.
- Local Docker volumes are used instead of private object storage.
- The AI Director relies on an external provider.
- Production deployment, monitoring and alerting remain future work.

---

## Production roadmap

Before production:

1. Replace CWASA with Cyrkil-owned or commercially licensed videos.
2. Implement and register the `licensed_video` provider.
3. Add Alembic database migrations.
4. Move generated media to private object storage.
5. Use a production secrets manager.
6. Deploy behind HTTPS.
7. Add monitoring, structured logs and alerting.
8. Add production backup and recovery procedures.
9. Validate signs with native sign-language experts.
10. Complete legal review of all production datasets and models.

---

## Third-party notices

See:

```text
THIRD_PARTY_NOTICES.md
docs/DATA_SOURCES.md
licenses/
```

Renaming, translating or converting an asset does not remove its original licence obligations.

---

## Related repositories

Updated repositories:

- https://github.com/helamoalla/hamnosys_to_sigml
- https://github.com/helamoalla/sl_generation_blender

Original references:

- https://github.com/carolNeves/HamNoSys2SiGML
- https://github.com/lanthaon/sl-animation-blender