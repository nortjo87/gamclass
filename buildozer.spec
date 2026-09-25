[app]
title = Gaming History
package.name = gaminghistory
package.domain = org.sonny

source.dir = .
source.include_exts = py,png,jpg,kv,atlas

version = 0.1

# requests butuh certifi/urllib3/idna/chardet ikut dibundel supaya HTTPS
# jalan di Android. pyjnius diperlukan Kivy sendiri di Android.
requirements = python3,kivy==2.3.0,requests,certifi,urllib3,idna,chardet,pyjnius

orientation = portrait
fullscreen = 0

# app ini hanya baca (GET) ke Firestore REST API -> cuma butuh INTERNET
android.permissions = INTERNET

android.api = 33
android.minapi = 21
android.ndk = 25b
android.accept_sdk_license = True
android.archs = arm64-v8a, armeabi-v7a

[buildozer]
log_level = 2
warn_on_root = 1
