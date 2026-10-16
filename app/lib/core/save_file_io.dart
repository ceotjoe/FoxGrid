import 'dart:io';

import 'package:path_provider/path_provider.dart';
import 'package:share_plus/share_plus.dart';

/// Writes [bytes] to the app's documents folder and opens the share sheet.
Future<String> saveBytes(String name, List<int> bytes, String mime) async {
  final dir = await getApplicationDocumentsDirectory();
  final file = File('${dir.path}/$name');
  await file.writeAsBytes(bytes, flush: true);
  await SharePlus.instance.share(
    ShareParams(
      files: [XFile(file.path, mimeType: mime)],
      subject: name,
    ),
  );
  return file.path;
}
