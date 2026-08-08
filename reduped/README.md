# Reduped

Reduped is a native Windows duplicate-media reviewer for an S3-compatible object store. It automatically validates inventory, reuses trustworthy evidence, builds certified generations, and keeps destructive actions locked until the displayed generation is proven current.

## Run

1. Download and extract the Windows artifact.
2. Copy `config.example.txt` to `config.txt`.
3. Fill in the endpoint, bucket, prefix, index key, and local credentials.
4. Start `Reduped.exe`.

Deletion is disabled by default. With `ALLOW_DELETE=NO`, the complete inventory, hashing, certification, preview, navigation, and exclusion workflow remains available, but destructive controls are visibly disabled.

## Build

The Windows artifact is built by CI with CMake, MSVC, and vcpkg. A compiler is not required on the target PC.

The code has three deliberate layers:

- `reduped_core`: deterministic inventory, SQLite persistence, matching, generation publication, actionability, and recovery.
- Windows services: object-store transport, native image/video evidence, and preview decoding.
- Win32 UI: one owner for state and controls; background operations communicate through revision-tagged messages.

No service endpoint, bucket, object prefix, public media address, credentials, or account-specific name is compiled into the application.
