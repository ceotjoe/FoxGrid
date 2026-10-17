# Flutter's Gradle plugin adds the engine rules. Keep Drift's generated sqlite glue and
# silence optional Play Core references that Flutter only touches for deferred components.
-dontwarn com.google.android.play.core.**
