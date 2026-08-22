package org.ksrace.senate2026

import android.app.Application
import org.ksrace.senate2026.work.Notifier
import org.ksrace.senate2026.work.RefreshScheduler

class KsApp : Application() {
    override fun onCreate() {
        super.onCreate()
        Notifier(this).ensureChannel()
        RefreshScheduler.ensureScheduled(this)
    }
}
