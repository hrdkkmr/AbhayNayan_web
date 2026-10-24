# ADR-005: Encrypt Room with SQLCipher and a Keystore-wrapped key

Status: **Accepted and implemented (Phase 6, 24 Oct 2026)**. It was verified on the `abhay_api36` emulator only. **Not yet verified on a physical phone.** Proposed 24 Oct 2026 (Phase 3).

## Decision

- **Library:** `net.zetetic:sqlcipher-android:4.12.0` (released 8 Dec 2025, Maven Central), used through Room's `openHelperFactory(SupportOpenHelperFactory(passphrase))`.
- **Passphrase:**
  - 256 random bits from `SecureRandom`, used as 64 lowercase hex ASCII characters;
  - processed by SQLCipher's default KDF; no custom cryptography;
  - never derived from a login token or any identifier.
- **Wrapping:**
  - The passphrase is wrapped by an Android Keystore AES-256-GCM key (alias `abhaynayan.db-key-wrap.v1`).
  - The key is non-exportable and is created in StrongBox when the phone has one (API 28+), with a software/TEE fallback.
  - The wrapped blob (`ANK1` + IV length + IV + ciphertext) is in `noBackupFilesDir/abhaynayan-db-key.v1`, written atomically (temp file, `fsync`, rename).
  - The raw passphrase is never written to disk, preferences or logs.
- **No user-authentication binding.** The key is usable without a screen unlock so the WorkManager sync can open the database in the background. This is a deliberate trade-off: the key protects data at rest on a locked device's storage, not against someone who can use the unlocked phone.

## Compatibility evidence (checked, not assumed)

| Requirement | Evidence |
|---|---|
| Room 2.7.2 integration | `SupportOpenHelperFactory` implements `androidx.sqlite.db.SupportSQLiteOpenHelper.Factory` (source of 4.12.0 inspected). Room builds and runs `runMigrationsAndValidate` 1→4, 2→4, 3→4 through it on the emulator |
| Dependency versions | The 4.12.0 POM depends on `androidx.sqlite:sqlite:2.2.0` and `kotlin-stdlib:2.2.10`, so Room's `androidx.sqlite` 2.5.1 and the project's Kotlin 2.2.20 are kept. 4.14+ depends on `androidx.sqlite` 2.6.2 and was not chosen, to avoid moving Room's SQLite layer |
| Minimum SDK | AAR manifest `minSdkVersion 21`; app `minSdk 26` |
| Build | `assembleDebug`, `lintDebug` (0 errors) and `assembleDebugAndroidTest` pass; ABIs arm64-v8a, armeabi-v7a, x86, x86_64 |
| Upgrades are transactional | SQLCipher's `SQLiteOpenHelper.getDatabaseLocked` wraps `onCreate`/`onUpgrade` in `beginTransaction … setTransactionSuccessful` (source inspected). A failed Room migration leaves the previous version unchanged |
| No deletion on a wrong key | `DefaultDatabaseErrorHandler.onCorruption` returns before deleting when `SQLiteDatabase.hasCodec()` (SQLCipher builds). The migration code passes its own no-op error handler as well. Instrumented test: a wrong key gives `KEY_REJECTED` and the file's SHA-256 is unchanged |
| Destructive migration | Not enabled (`fallbackToDestructiveMigration` is never called). SQLCipher's `minimumSupportedVersion` is left at its default 0, which never deletes |
| Size | About 23.6 MB of uncompressed native libraries across the four ABIs (6.6 MB for arm64-v8a alone). The debug APK is 40.0 MB |

## Lifecycle

| Situation | Behaviour |
|---|---|
| First start, no database | Create the key, then an empty encrypted database (`abhaynayan-secure.db`) |
| Normal start or process restart | Load and unwrap the key and open the database. This is done once per process, off the main thread, by `LocalStore`, and the UI and `SyncWorker` both wait for it. The passphrase stays in memory for the process lifetime because Room may reopen the database |
| Upgrade from a plaintext database (`abhaynayan-local.db`, schema v1, v2 or v3) | 1. Create the key. 2. `sqlcipher_export` into `abhaynayan-secure.db.migrating`, copying `user_version`. 3. Verify the copy: per table, row count plus SHA-256 over every value in rowid order, then `PRAGMA integrity_check`. 4. Rename the copy into place. 5. Delete the plaintext file and its `-wal`/`-shm`/`-journal`. 6. Room then runs its own v1/v2/v3 → v4 migrations inside the upgrade transaction |
| Failure during the plaintext move | Only the temporary copy is deleted. The plaintext records are kept (opening them lets SQLite merge the WAL into the main file, so the bytes can change but the content does not). The screen says "Records not yet moved", and a retry runs the move again |
| Interrupted after the rename (both files exist) | The two are compared. If they match, the plaintext file is deleted and the store opens. If they differ, `MIGRATION_CONFLICT`: both are kept and nothing opens |
| Key file missing or Keystore key gone | `KEY_MISSING`. No new key is created, because an encrypted database exists. Nothing is deleted |
| Key file altered, or wrapped by another key | `KEY_UNUSABLE` (GCM authentication fails) |
| Key unwraps but SQLCipher rejects it | `KEY_REJECTED` ("file is not a database") |
| A plaintext file where the encrypted one should be | `UNEXPECTED_PLAINTEXT`. It is refused and left untouched; there is never a plaintext fallback |
| Recovery from a key failure | Only an explicit, confirmed "Set aside the locked records and start empty". It **moves** the encrypted database and wrapped key into `databases/set-aside/<time>/` and does not delete them. Nothing resets automatically |
| Debug vs release | Identical. No debug key, no fixed fallback key, no plaintext debug mode |

`allowBackup=false`, `fullBackupContent=false` and the data-extraction rules are unchanged, so neither the database nor the wrapped key is backed up. If app data were copied to another phone, its Keystore would not have the key, and the result is `KEY_MISSING`, not an empty store.

## What this does not protect against

- Malware or a person with code execution as the app on an unlocked phone. The key is usable without user authentication.
- A rooted phone or a compromised OS, which can read process memory or use the Keystore as the app.
- The plaintext file left by earlier versions. It is deleted after a verified move, but deletion on flash storage is not secure erasure. Earlier versions told users not to store real patient data, and the prototype still does.
- A content hash in a record ([record_contract.md §8](../record_contract.md)) is not a signature. Anyone who can write the database can rewrite a record and its hash together.

## Consequences

The APK grows by the SQLCipher native libraries (measured above). Losing the Keystore key, for example after a factory reset or an app-data clear, makes the local records unrecoverable on that phone. The record content was never synced, because contract 1.x has no endpoint for it ([API_CONTRACT.md](../API_CONTRACT.md)), so set-aside records cannot be restored from the server either.

## Verification

- **JVM** (`SecureStorageTest`):
  - key-file create, reload and reuse;
  - missing, corrupted or foreign key files;
  - open-plan decisions;
  - plaintext header detection;
  - failure messages.
- **Instrumented** (`SecureDatabaseInstrumentedTest`, 13 tests, emulator `abhay_api36`, API 36):
  - fresh store encrypted and readable after restart;
  - plain SQLite and SQLCipher without the key both fail;
  - wrong key, missing key file and removed Keystore key all fail safely with the file unchanged;
  - set-aside keeps the files;
  - plaintext at the secure path is refused;
  - v3 plaintext with 4 records migrates with every column identical;
  - v1 and v2 plaintext migrate;
  - an injected crash and a damaged copy both keep the source, and a retry succeeds;
  - an interrupted migration completes when the copies match and is refused when they differ;
  - Room 1→4, 2→4 and 3→4 validate under SQLCipher;
  - triggers;
  - atomic and concurrent saves;
  - network failure during sync.
- **Emulator upgrade of the installed Phase 5 app** (5 records, plaintext v3 with WAL):
  - The first attempt failed safely: `ATTACH` could not create the target file. The app showed "Records not yet moved" and kept the source, and the cause was fixed.
  - The second attempt migrated all 5 records. The encrypted file has no SQLite header, and the plaintext files are gone.
  - Legacy records display with their stored values and "older record, history not verifiable".
  - A new record shows "unchanged since it was saved".
  - Records survive a forced stop and restart.
