package org.ksrace.senate2026.work

/**
 * Something in the race worth interrupting the user for.
 *
 * Produced by [ChangeDetector] and rendered by [Notifier]. It lives in its own
 * file because the detector decides what an event *is* while the notifier only
 * knows how to show one — keeping the type next to the notifier made the
 * detector look like it depended on Android, which it does not.
 */
data class RaceEvent(val id: String, val title: String, val body: String)
