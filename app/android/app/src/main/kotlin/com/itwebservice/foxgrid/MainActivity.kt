package com.itwebservice.foxgrid

import android.app.NotificationChannel
import android.app.NotificationManager
import android.os.Build
import android.os.Bundle
import io.flutter.embedding.android.FlutterActivity

class MainActivity : FlutterActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        createTransmissionChannel()
    }

    /** The server names this channel in its push messages; without it Android falls back to a silent default. */
    private fun createTransmissionChannel() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
        val channel = NotificationChannel(
            "transmission",
            "Aussendung",
            NotificationManager.IMPORTANCE_HIGH,
        ).apply {
            description = "Meldung, wenn der Störer sendet"
            enableVibration(true)
        }
        getSystemService(NotificationManager::class.java).createNotificationChannel(channel)
    }
}
