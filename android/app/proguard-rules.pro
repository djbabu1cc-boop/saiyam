# Release builds are not minified (see app/build.gradle.kts); this file is
# kept for anyone who enables R8. PDFBox loads classes reflectively:
-keep class com.tom_roush.pdfbox.** { *; }
-dontwarn com.gemalto.jp2.**
-dontwarn org.bouncycastle.**
