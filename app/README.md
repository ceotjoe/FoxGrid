# FoxGrid app

Flutter client (Android, iOS, web control room) for FoxGrid. See [docs/development/app.md](../docs/development/app.md)
for the structure and conventions, and the [project README](../README.md) for the big picture.

```bash
flutter pub get
flutter run -d chrome          # web control room
flutter run -d emulator-5554   # Android emulator (server URL http://10.0.2.2:8000)
flutter analyze && flutter test
```
