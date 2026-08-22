package org.ksrace.senate2026.ui

import android.Manifest
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.BackHandler
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.AccountBalance
import androidx.compose.material.icons.filled.Article
import androidx.compose.material.icons.filled.HowToVote
import androidx.compose.material.icons.filled.MoreHoriz
import androidx.compose.material.icons.filled.Poll
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import org.ksrace.senate2026.ui.ads.AdsScreen
import org.ksrace.senate2026.ui.ground.GroundScreen
import org.ksrace.senate2026.ui.home.HomeScreen
import org.ksrace.senate2026.ui.money.MoneyScreen
import org.ksrace.senate2026.ui.more.MoreDestination
import org.ksrace.senate2026.ui.more.MoreScreen
import org.ksrace.senate2026.ui.news.NewsScreen
import org.ksrace.senate2026.ui.polls.PollsScreen
import org.ksrace.senate2026.ui.results.ResultsScreen
import org.ksrace.senate2026.ui.settings.SettingsScreen
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
 * Five tabs and one level of drill-down, with no navigation library.
 *
 * There is no deep linking and no back stack worth persisting beyond "am I in a
 * sub-screen", so a nav graph would be ceremony. Both pieces of state survive
 * rotation through rememberSaveable, and the system back gesture is wired to
 * leaving a sub-screen rather than the app.
 */
private enum class Tab(val label: String, val icon: ImageVector) {
    HOME("Race", Icons.Filled.HowToVote),
    POLLS("Polls", Icons.Filled.Poll),
    MONEY("Money", Icons.Filled.AccountBalance),
    NEWS("News", Icons.Filled.Article),
    MORE("More", Icons.Filled.MoreHoriz),
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun AppRoot() {
    val viewModel: RaceViewModel = viewModel()
    val snapshot by viewModel.snapshot.collectAsStateWithLifecycle()
    val now by viewModel.now.collectAsStateWithLifecycle()

    var selected by rememberSaveable { mutableStateOf(Tab.HOME) }
    var detail by rememberSaveable { mutableStateOf<MoreDestination?>(null) }

    BackHandler(enabled = detail != null) { detail = null }

    Scaffold(
        topBar = {
            detail?.let { destination ->
                TopAppBar(
                    title = { Text(destination.title) },
                    navigationIcon = {
                        IconButton(onClick = { detail = null }) {
                            Icon(
                                imageVector = Icons.AutoMirrored.Filled.ArrowBack,
                                contentDescription = "Back",
                            )
                        }
                    },
                )
            }
        },
        bottomBar = {
            NavigationBar {
                Tab.entries.forEach { tab ->
                    NavigationBarItem(
                        selected = tab == selected && detail == null,
                        onClick = {
                            selected = tab
                            detail = null
                        },
                        icon = { Icon(tab.icon, contentDescription = null) },
                        label = { Text(tab.label) },
                    )
                }
            }
        },
    ) { insets ->
        val content = Modifier.padding(insets)

        val openDetail = detail
        if (openDetail != null) {
            when (openDetail) {
                MoreDestination.RESULTS -> ResultsScreen(
                    snapshot = snapshot,
                    now = now,
                    onNeedsPolling = viewModel::startResultsPolling,
                    modifier = content,
                )
                MoreDestination.ADS -> AdsScreen(snapshot, now, content)
                MoreDestination.GROUND -> GroundScreen(snapshot, now, content)
                MoreDestination.SETTINGS -> SettingsScreen(
                    snapshot = snapshot,
                    now = now,
                    onRefresh = viewModel::refresh,
                    modifier = content,
                )
            }
            return@Scaffold
        }

        when (selected) {
            Tab.HOME -> HomeScreen(
                snapshot = snapshot,
                now = now,
                onRefresh = viewModel::refresh,
                onResultsVisible = viewModel::startResultsPolling,
                onOpenResults = { detail = MoreDestination.RESULTS },
                modifier = content,
            )
            Tab.POLLS -> PollsScreen(snapshot = snapshot, now = now, modifier = content)
            Tab.MONEY -> MoneyScreen(snapshot = snapshot, now = now, modifier = content)
            Tab.NEWS -> NewsScreen(snapshot = snapshot, now = now, modifier = content)
            Tab.MORE -> MoreScreen(
                snapshot = snapshot,
                onOpen = { detail = it },
                modifier = content,
            )
        }
    }
}
