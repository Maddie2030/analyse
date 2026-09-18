package com.mreader.android.ui

import android.net.Uri
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.LibraryBooks
import androidx.compose.material.icons.filled.Explore
import androidx.compose.material.icons.filled.Login
import androidx.compose.material.icons.filled.Notifications
import androidx.compose.material.icons.filled.Search
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.getValue
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalUriHandler
import androidx.compose.ui.unit.dp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.navigation.NavGraph.Companion.findStartDestination
import androidx.navigation.NavHostController
import androidx.navigation.NavType
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController
import androidx.navigation.navArgument
import com.mreader.android.ui.screens.*
import com.mreader.android.ui.theme.*

private data class BottomDestination(val route: String, val label: String, val icon: ImageVector)

object Routes {
    const val CATALOG = "catalog"
    const val SEARCH = "search"
    const val LIBRARY = "library"
    const val NOTIFICATIONS = "notifications"
    const val LOGIN = "login"
    const val REGISTER = "register"
    const val SETTINGS = "settings"
    const val SERIES = "series/{slug}"
    const val READER = "reader/{seriesSlug}/{chapterSlug}"
    const val WEB_READER = "web-reader/{seriesSlug}/{chapterSlug}"

    fun series(slug: String) = "series/${Uri.encode(slug)}"
    fun reader(seriesSlug: String, chapterSlug: String) =
        "reader/${Uri.encode(seriesSlug)}/${Uri.encode(chapterSlug)}"
    fun webReader(seriesSlug: String, chapterSlug: String) =
        "web-reader/${Uri.encode(seriesSlug)}/${Uri.encode(chapterSlug)}"
}

@Composable
fun MReaderApp(appViewModel: AppViewModel) {
    val navController = rememberNavController()
    val uriHandler = LocalUriHandler.current
    val currentUser by appViewModel.user.collectAsStateWithLifecycle()
    val unreadCount by appViewModel.unreadNotifications.collectAsStateWithLifecycle()
    val contentEpoch by appViewModel.contentEpoch.collectAsStateWithLifecycle()
    val entry by navController.currentBackStackEntryAsState()
    val route = entry?.destination?.route.orEmpty()
    val showBottomBar = route !in setOf(Routes.READER, Routes.WEB_READER, Routes.LOGIN, Routes.REGISTER)
    val lifecycleOwner = LocalLifecycleOwner.current

    // Refresh the alert badge only when the app returns to the foreground. This
    // mirrors the web feed freshness without keeping a polling loop alive.
    DisposableEffect(lifecycleOwner, currentUser?.id) {
        val observer = LifecycleEventObserver { _, event ->
            if (event == Lifecycle.Event.ON_RESUME) {
                appViewModel.refreshForegroundContent()
            }
        }
        lifecycleOwner.lifecycle.addObserver(observer)
        onDispose { lifecycleOwner.lifecycle.removeObserver(observer) }
    }

    fun accountRoute(): String = if (currentUser == null) Routes.LOGIN else Routes.SETTINGS

    Scaffold(
        containerColor = Ink950,
        bottomBar = {
            if (showBottomBar) MainBottomBar(navController, route, signedIn = currentUser != null, unreadCount = unreadCount)
        },
    ) { padding ->
        NavHost(navController = navController, startDestination = Routes.CATALOG) {
            composable(Routes.CATALOG) {
                CatalogScreen(
                    repository = appViewModel.repository,
                    user = appViewModel.user,
                    refreshEpoch = contentEpoch,
                    contentPadding = padding,
                    onSeries = { navController.navigate(Routes.series(it)) },
                    onRead = { s, c -> navController.navigate(Routes.reader(s, c)) },
                    onLogin = { navController.navigate(accountRoute()) },
                    onAnnouncementLink = { link ->
                        if (link.startsWith('/')) {
                            runCatching { navController.navigate(link.removePrefix("/")) }
                        } else {
                            runCatching { uriHandler.openUri(link) }
                        }
                    },
                )
            }
            composable(Routes.SEARCH) {
                SearchScreen(
                    repository = appViewModel.repository,
                    refreshEpoch = contentEpoch,
                    contentPadding = padding,
                    onSeries = { navController.navigate(Routes.series(it)) },
                    onAccount = { navController.navigate(accountRoute()) },
                )
            }
            composable(Routes.LIBRARY) {
                LibraryScreen(
                    repository = appViewModel.repository,
                    user = appViewModel.user,
                    refreshEpoch = contentEpoch,
                    contentPadding = padding,
                    onSeries = { navController.navigate(Routes.series(it)) },
                    onRead = { s, c -> navController.navigate(Routes.reader(s, c)) },
                    onLogin = { navController.navigate(Routes.LOGIN) },
                    onAccount = { navController.navigate(accountRoute()) },
                )
            }
            composable(Routes.NOTIFICATIONS) {
                NotificationsScreen(
                    appViewModel = appViewModel,
                    refreshEpoch = contentEpoch,
                    contentPadding = padding,
                    onReadChapter = { s, c -> navController.navigate(Routes.reader(s, c)) },
                    onLogin = { navController.navigate(Routes.LOGIN) },
                    onAccount = { navController.navigate(accountRoute()) },
                )
            }
            composable(Routes.LOGIN) {
                LoginScreen(
                    appViewModel = appViewModel,
                    onDone = {
                        navController.popBackStack()
                        if (navController.currentDestination == null) navController.navigate(Routes.CATALOG)
                    },
                    onGuest = { navController.popBackStack() },
                    onRegister = { navController.navigate(Routes.REGISTER) },
                )
            }
            composable(Routes.REGISTER) {
                RegisterScreen(
                    appViewModel = appViewModel,
                    onDone = {
                        navController.navigate(Routes.CATALOG) {
                            popUpTo(Routes.CATALOG) { inclusive = true }
                        }
                    },
                    onLogin = { navController.popBackStack() },
                )
            }
            composable(Routes.SETTINGS) {
                SettingsScreen(
                    appViewModel = appViewModel,
                    contentPadding = padding,
                    onLogin = { navController.navigate(Routes.LOGIN) },
                )
            }
            composable(
                Routes.SERIES,
                arguments = listOf(navArgument("slug") { type = NavType.StringType }),
            ) { backStack ->
                SeriesScreen(
                    repository = appViewModel.repository,
                    user = appViewModel.user,
                    refreshEpoch = contentEpoch,
                    slug = Uri.decode(backStack.arguments?.getString("slug").orEmpty()),
                    contentPadding = padding,
                    onBack = { navController.popBackStack() },
                    onRead = { s, c -> navController.navigate(Routes.reader(s, c)) },
                    onLogin = { navController.navigate(Routes.LOGIN) },
                    onContentChanged = { appViewModel.notifyContentChanged() },
                )
            }
            composable(
                Routes.READER,
                arguments = listOf(
                    navArgument("seriesSlug") { type = NavType.StringType },
                    navArgument("chapterSlug") { type = NavType.StringType },
                ),
            ) { backStack ->
                val seriesSlug = Uri.decode(backStack.arguments?.getString("seriesSlug").orEmpty())
                val chapterSlug = Uri.decode(backStack.arguments?.getString("chapterSlug").orEmpty())
                ReaderScreen(
                    appViewModel = appViewModel,
                    seriesSlug = seriesSlug,
                    chapterSlug = chapterSlug,
                    onBack = { navController.popBackStack() },
                    onChapter = { s, c ->
                        navController.navigate(Routes.reader(s, c)) {
                            popUpTo(Routes.READER) { inclusive = true }
                        }
                    },
                    onLogin = { navController.navigate(Routes.LOGIN) },
                    onWebFallback = { navController.navigate(Routes.webReader(seriesSlug, chapterSlug)) },
                )
            }
            composable(
                Routes.WEB_READER,
                arguments = listOf(
                    navArgument("seriesSlug") { type = NavType.StringType },
                    navArgument("chapterSlug") { type = NavType.StringType },
                ),
            ) { backStack ->
                WebReaderScreen(
                    appViewModel = appViewModel,
                    seriesSlug = Uri.decode(backStack.arguments?.getString("seriesSlug").orEmpty()),
                    chapterSlug = Uri.decode(backStack.arguments?.getString("chapterSlug").orEmpty()),
                    onBack = { navController.popBackStack() },
                )
            }
        }
    }
}


private fun navigateTopLevel(navController: NavHostController, targetRoute: String) {
    if (navController.currentDestination?.route == targetRoute) return

    // Browse is the graph root. Prefer an explicit pop to the existing Catalog
    // entry so a tap always leaves Series/Settings/Search/Library immediately
    // instead of depending on saved-state restoration to choose the visible page.
    if (targetRoute == Routes.CATALOG) {
        if (!navController.popBackStack(Routes.CATALOG, inclusive = false)) {
            navController.navigate(Routes.CATALOG) {
                popUpTo(navController.graph.findStartDestination().id) { inclusive = true }
                launchSingleTop = true
            }
        }
        return
    }

    navController.navigate(targetRoute) {
        popUpTo(navController.graph.findStartDestination().id) { saveState = true }
        launchSingleTop = true
        restoreState = true
    }
}

@Composable
private fun MainBottomBar(navController: NavHostController, route: String, signedIn: Boolean, unreadCount: Int) {
    val destinations = buildList {
        add(BottomDestination(Routes.CATALOG, "Browse", Icons.Default.Explore))
        add(BottomDestination(Routes.SEARCH, "Search", Icons.Default.Search))
        if (signedIn) {
            add(BottomDestination(Routes.LIBRARY, "Library", Icons.AutoMirrored.Filled.LibraryBooks))
            add(BottomDestination(Routes.NOTIFICATIONS, "Alerts", Icons.Default.Notifications))
        } else {
            add(BottomDestination(Routes.LOGIN, "Sign in", Icons.Default.Login))
        }
    }

    NavigationBar(
        containerColor = Ink900.copy(alpha = .98f),
        contentColor = Ink300,
        tonalElevation = 0.dp,
    ) {
        destinations.forEach { item ->
            val atDestination = route == item.route
            val selected = atDestination
            NavigationBarItem(
                selected = selected,
                onClick = { navigateTopLevel(navController, item.route) },
                icon = {
                    BadgedBox(
                        badge = {
                            if (item.route == Routes.NOTIFICATIONS && unreadCount > 0) {
                                Badge(containerColor = Brand600, contentColor = androidx.compose.ui.graphics.Color.White) {
                                    Text(if (unreadCount > 99) "99+" else unreadCount.toString())
                                }
                            }
                        },
                    ) { Icon(item.icon, contentDescription = item.label) }
                },
                label = { Text(item.label) },
                colors = NavigationBarItemDefaults.colors(
                    selectedIconColor = Brand400,
                    selectedTextColor = Brand400,
                    indicatorColor = Brand950.copy(alpha = .75f),
                    unselectedIconColor = Ink400,
                    unselectedTextColor = Ink400,
                ),
            )
        }
    }
}
