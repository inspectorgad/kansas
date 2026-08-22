package org.ksrace.senate2026.ui

import android.Manifest
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.AccountBalance
import androidx.compose.material.icons.filled.Article
import androidx.compose.material.icons.filled.HowToVote
import androidx.compose.material.icons.filled.Poll
import androidx.compose.material3.Icon
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import org.ksrace.senate2026.ui.home.HomeScreen
import org.ksrace.senate2026.ui.money.MoneyScreen
import org.ksrace.senate2026.ui.news.NewsScreen
import org.ksrace.senate2026.ui.polls.PollsScreen
import org.ksrace.senate2026.ui.theme.KansasSenateTheme

class MainActivity : ComponentActivity() {

    private val requestNotifications =
        registerForActivityResult(ActivityResultContracts.RequestPermission()) { /* either way is fine */ }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            requestNotifications.launch(Manifest.permission.POST_NOTIFICATIONS)
        }

        setContent {
            KansasSenateTheme {
                AppRoot()
            }
        }
    }
}

/**
 * Four tabs, no navigation library.
 *
 * The app is a flat set of views over one snapshot with no deep linking and no
 * back stack worth preserving, so a nav graph would be pure ceremony. Tab state
 * survives rotation via rememberSaveable.
 */
private enum class Tab(val label: String, val icon: ImageVector) {
    HOME("Race", Icons.Filled.HowToVote),
    POLLS("Polls", Icons.Filled.Poll),
    MONEY("Money", Icons.Filled.AccountBalance),
    NEWS("News", Icons.Filled.Article),
}

@Composable
private fun AppRoot() {
    val viewModel: RaceViewModel = viewModel()
    val snapshot by viewModel.snapshot.collectAsStateWithLifecycle()
    val now by viewModel.now.collectAsStateWithLifecycle()
    var selected by rememberSaveable { mutableStateOf(Tab.HOME) }

    Scaffold(
        bottomBar = {
            NavigationBar {
                Tab.entries.forEach { tab ->
                    NavigationBarItem(
                        selected = tab == selected,
                        onClick = { selected = tab },
                        icon = { Icon(tab.icon, contentDescription = null) },
                        label = { Text(tab.label) },
                    )
                }
            }
        },
    ) { insets ->
        val content = Modifier.padding(insets)
        when (selected) {
            Tab.HOME -> HomeScreen(
                snapshot = snapshot,
                now = now,
                onRefresh = viewModel::refresh,
                onResultsVisible = viewModel::startResultsPolling,
                modifier = content,
            )
            Tab.POLLS -> PollsScreen(snapshot = snapshot, now = now, modifier = content)
            Tab.MONEY -> MoneyScreen(snapshot = snapshot, now = now, modifier = content)
            Tab.NEWS -> NewsScreen(snapshot = snapshot, now = now, modifier = content)
        }
    }
}
