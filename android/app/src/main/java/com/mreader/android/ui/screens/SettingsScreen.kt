package com.mreader.android.ui.screens

import androidx.annotation.DrawableRes
import androidx.compose.foundation.Image
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.CloudDone
import androidx.compose.material.icons.filled.CloudOff
import androidx.compose.material.icons.filled.DeleteSweep
import androidx.compose.material.icons.filled.Storage
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Lock
import androidx.compose.material.icons.filled.Person
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.mreader.android.R
import com.mreader.android.ui.AppViewModel
import com.mreader.android.ui.components.ResponsiveFrame
import com.mreader.android.ui.components.SectionHeading
import com.mreader.android.ui.theme.*
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.launch

private data class AvatarOption(val key: String, val label: String, val description: String, @DrawableRes val image: Int)
private val avatarOptions = listOf(
    AvatarOption("skull", "Skull", "Default reader mark.", R.drawable.avatar_skull),
    AvatarOption("bard", "Bard", "Songs, support and travelling-story energy.", R.drawable.avatar_bard),
    AvatarOption("cleric", "Cleric", "Calm, faithful and temple-guarded resolve.", R.drawable.avatar_cleric),
    AvatarOption("fire_wielder", "Fire Wielder", "Explosive magic and burning combat focus.", R.drawable.avatar_fire_wielder),
    AvatarOption("king", "King", "Royal instinct, command and ruling presence.", R.drawable.avatar_king),
    AvatarOption("paladin", "Paladin", "Holy armor, discipline and frontline courage.", R.drawable.avatar_paladin),
    AvatarOption("shadow_rogue", "Shadow Rogue", "Stealth, night hunts and dangerous precision.", R.drawable.avatar_shadow_rogue),
    AvatarOption("sorcerer", "Sorcerer", "Arcane mystery, starlight and hidden power.", R.drawable.avatar_sorcerer),
    AvatarOption("swordsman", "Swordsman", "Blade mastery, focus and clean striking force.", R.drawable.avatar_swordsman),
)

@Composable
fun SettingsScreen(appViewModel: AppViewModel, contentPadding: PaddingValues, onLogin: () -> Unit) {
    val user by appViewModel.user.collectAsStateWithLifecycle()
    val cacheEpoch by appViewModel.cacheEpoch.collectAsStateWithLifecycle()
    val repository = appViewModel.repository
    val readingView by appViewModel.reading.collectAsStateWithLifecycle()
    val logoutProblem by appViewModel.logoutProblem.collectAsStateWithLifecycle()
    var confirmLogout by remember { mutableStateOf(false) }
    val initial = remember { repository.serverConfig() }
    var connected by remember { mutableStateOf<Boolean?>(null) }
    var profileStatus by remember { mutableStateOf<String?>(null) }
    var busy by remember { mutableStateOf(false) }
    var avatarBusy by remember { mutableStateOf(false) }
    var cacheBytes by remember { mutableLongStateOf(0L) }
    var cacheEntries by remember { mutableIntStateOf(0) }
    var clearingCache by remember { mutableStateOf(false) }
    var cacheStatus by remember { mutableStateOf<String?>(null) }
    val scope = rememberCoroutineScope()

    if (confirmLogout) AlertDialog(
        onDismissRequest = { confirmLogout = false },
        title = { Text("Sign out?") },
        text = { Text(if (repository.reading.hasPrivatePending())
            "Unsynced reading changes will be discarded from this device. Server-saved progress will remain."
            else "Your private reading data and downloaded pages will be removed from this device.") },
        confirmButton = { TextButton(onClick = { confirmLogout = false; appViewModel.logout() }) { Text("Sign out") } },
        dismissButton = { TextButton(onClick = { confirmLogout = false }) { Text("Keep reading") } },
    )

    suspend fun checkConnection() {
        busy = true
        connected = null
        try {
            repository.testServerConfig(initial.baseUrl, initial.imageCdnUrl)
            connected = true
        } catch (cancelled: CancellationException) {
            throw cancelled
        } catch (_: Throwable) {
            connected = false
        } finally {
            busy = false
        }
    }

    suspend fun refreshCacheUsage() {
        val usage = repository.downloadedCacheUsage()
        cacheBytes = usage.bytes
        cacheEntries = usage.entries
    }

    LaunchedEffect(Unit) {
        checkConnection()
    }

    LaunchedEffect(cacheEpoch, user?.id) {
        runCatching { refreshCacheUsage() }
    }

    ResponsiveFrame(maxContentWidth = 760.dp) { edgePadding ->
        Column(
        Modifier.fillMaxSize().padding(contentPadding).verticalScroll(rememberScrollState()).imePadding().padding(horizontal = edgePadding, vertical = 14.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        SectionHeading("Personal", "Profile & settings", "The same account identity and connection used by the MReader web application.")

        val signedInUser = user
        if (signedInUser == null) {
            Surface(color = Ink900, shape = RoundedCornerShape(18.dp), border = androidx.compose.foundation.BorderStroke(1.dp, Ink800)) {
                Column(Modifier.padding(18.dp), verticalArrangement = Arrangement.spacedBy(11.dp), horizontalAlignment = Alignment.CenterHorizontally) {
                    Icon(Icons.Default.Person, null, tint = Brand400, modifier = Modifier.size(36.dp))
                    Text("You are browsing as a guest", color = Ink50, style = MaterialTheme.typography.titleMedium)
                    Text("Sign in to sync your avatar, library, ratings and progress.", color = Ink400, style = MaterialTheme.typography.bodySmall)
                    Button(onClick = onLogin, colors = ButtonDefaults.buttonColors(containerColor = Brand600), shape = RoundedCornerShape(12.dp)) { Text("Sign in") }
                }
            }
        } else {
            Surface(color = Ink900.copy(alpha = 0.72f), shape = RoundedCornerShape(18.dp), border = androidx.compose.foundation.BorderStroke(1.dp, Ink800)) {
                Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                    Text("Choose your reader mark", style = MaterialTheme.typography.titleMedium, color = Ink50)
                    Text("Choose from the same profile avatar set available on the web application.", color = Ink500, style = MaterialTheme.typography.bodySmall)
                    BoxWithConstraints(Modifier.fillMaxWidth()) {
                        val columns = if (maxWidth < 420.dp) 2 else 3
                        Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                            avatarOptions.chunked(columns).forEach { row ->
                                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                                    row.forEach { option ->
                                        AvatarCard(
                                            option = option,
                                            selected = signedInUser.avatarKey == option.key,
                                            enabled = !avatarBusy,
                                            modifier = Modifier.weight(1f),
                                            onClick = {
                                                avatarBusy = true; profileStatus = null
                                                scope.launch {
                                                    try {
                                                        appViewModel.updateAvatar(option.key).getOrThrow()
                                                        profileStatus = "Avatar updated."
                                                    } catch (cancelled: CancellationException) { throw cancelled }
                                                    catch (failure: Throwable) { profileStatus = failure.message ?: "Avatar update failed." }
                                                    finally { avatarBusy = false }
                                                }
                                            },
                                        )
                                    }
                                    repeat(columns - row.size) { Spacer(Modifier.weight(1f)) }
                                }
                            }
                        }
                    }
                    profileStatus?.let { Text(it, color = if (it.contains("failed", true)) MaterialTheme.colorScheme.error else Brand300, style = MaterialTheme.typography.bodySmall) }
                }
            }

            Surface(color = Ink900.copy(alpha = 0.72f), shape = RoundedCornerShape(18.dp), border = androidx.compose.foundation.BorderStroke(1.dp, Ink800)) {
                Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(11.dp)) {
                    if (signedInUser.role == "admin") {
                        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.End) {
                            Icon(Icons.Default.VerifiedUser, contentDescription = "Administrator account", tint = Gold400, modifier = Modifier.size(20.dp))
                        }
                    }
                    LockedAccountField("Username", signedInUser.username)
                    LockedAccountField("Email", signedInUser.email)
                    Text("Account identifiers are locked, matching the web profile.", color = Ink500, style = MaterialTheme.typography.bodySmall)
                    com.mreader.android.ui.components.ReadingSyncStatus(repository, readingView)
                    logoutProblem?.let { Text(it, color = MaterialTheme.colorScheme.error) }
                    OutlinedButton(onClick = { confirmLogout = true }, colors = ButtonDefaults.outlinedButtonColors(contentColor = Brand300)) { Text("Sign out") }
                }
            }
        }

        Surface(color = Ink900, shape = RoundedCornerShape(18.dp), border = androidx.compose.foundation.BorderStroke(1.dp, Ink800)) {
            Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    Icon(Icons.Default.Storage, contentDescription = null, tint = Brand400)
                    Column(Modifier.weight(1f)) {
                        Text("Local app data", style = MaterialTheme.typography.titleMedium, color = Ink50)
                        Text(
                            if (cacheEntries == 0) "No downloaded cache" else "${formatCacheBytes(cacheBytes)} · $cacheEntries cached items",
                            color = Ink400,
                            style = MaterialTheme.typography.bodySmall,
                        )
                    }
                }
                Text(
                    if (signedInUser != null)
                        "Catalog data is kept locally for smoother navigation. Encoded chapter data you read is retained for up to 24 hours and refreshed as needed."
                    else
                        "Catalog data is cached for smoother navigation. Sign in to enable persistent 24-hour chapter caching.",
                    color = Ink500,
                    style = MaterialTheme.typography.bodySmall,
                )
                OutlinedButton(
                    onClick = {
                        clearingCache = true
                        cacheStatus = null
                        scope.launch {
                            try {
                                appViewModel.clearDownloadedData()
                                refreshCacheUsage()
                                cacheStatus = "Downloaded data cleared."
                            } catch (cancelled: CancellationException) {
                                throw cancelled
                            } catch (failure: Throwable) {
                                cacheStatus = failure.message ?: "Could not clear downloaded data."
                            } finally {
                                clearingCache = false
                            }
                        }
                    },
                    enabled = !clearingCache && cacheEntries > 0,
                    colors = ButtonDefaults.outlinedButtonColors(contentColor = Brand300),
                ) {
                    Icon(Icons.Default.DeleteSweep, contentDescription = null, modifier = Modifier.size(18.dp))
                    Spacer(Modifier.width(7.dp))
                    Text(if (clearingCache) "Clearing…" else "Clear downloaded data")
                }
                cacheStatus?.let { Text(it, color = Ink400, style = MaterialTheme.typography.labelSmall) }
            }
        }

        Surface(color = Ink900, shape = RoundedCornerShape(18.dp), border = androidx.compose.foundation.BorderStroke(1.dp, Ink800)) {
            Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                Row(
                    Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Row(horizontalArrangement = Arrangement.spacedBy(10.dp), verticalAlignment = Alignment.CenterVertically) {
                        val isConnected = connected == true
                        Icon(
                            if (isConnected) Icons.Default.CloudDone else Icons.Default.CloudOff,
                            contentDescription = null,
                            tint = if (isConnected) Brand400 else if (connected == false) MaterialTheme.colorScheme.error else Ink500,
                        )
                        Column {
                            Text("Connection", style = MaterialTheme.typography.titleMedium, color = Ink50)
                            Text(
                                when (connected) {
                                    true -> "Connected"
                                    false -> "Server under maintenance."
                                    null -> "Checking…"
                                },
                                color = when (connected) {
                                    true -> Brand300
                                    false -> MaterialTheme.colorScheme.error
                                    null -> Ink500
                                },
                                style = MaterialTheme.typography.bodySmall,
                            )
                        }
                    }
                    IconButton(
                        onClick = { scope.launch { checkConnection() } },
                        enabled = !busy,
                    ) {
                        Icon(Icons.Default.Refresh, contentDescription = "Check connection", tint = Ink300)
                    }
                }
            }
        }
    }
    }
}

@Composable
private fun AvatarCard(option: AvatarOption, selected: Boolean, enabled: Boolean, modifier: Modifier, onClick: () -> Unit) {
    val shape = RoundedCornerShape(14.dp)
    Column(
        modifier
            .height(226.dp)
            .clip(shape)
            .border(1.dp, if (selected) Brand500 else Ink800, shape)
            .clickable(enabled = enabled, onClick = onClick)
            .padding(9.dp),
        verticalArrangement = Arrangement.spacedBy(4.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Box(Modifier.fillMaxWidth().height(96.dp), contentAlignment = Alignment.Center) {
            Image(
                painterResource(option.image),
                option.label,
                Modifier.size(94.dp).clip(CircleShape).border(1.dp, if (selected) Brand500 else Ink700, CircleShape),
                contentScale = ContentScale.Crop,
            )
        }
        Box(Modifier.fillMaxWidth().height(38.dp), contentAlignment = Alignment.Center) {
            Text(
                option.label,
                color = Ink50,
                style = MaterialTheme.typography.labelMedium,
                maxLines = 2,
                textAlign = TextAlign.Center,
            )
        }
        Box(Modifier.fillMaxWidth().height(48.dp), contentAlignment = Alignment.TopCenter) {
            Text(
                option.description,
                color = Ink500,
                style = MaterialTheme.typography.labelSmall,
                maxLines = 3,
                textAlign = TextAlign.Center,
            )
        }
        Box(Modifier.fillMaxWidth().height(18.dp), contentAlignment = Alignment.Center) {
            Text(
                "Selected",
                color = if (selected) Brand300 else Color.Transparent,
                style = MaterialTheme.typography.labelSmall,
                textAlign = TextAlign.Center,
            )
        }
    }
}

@Composable
private fun LockedAccountField(label: String, value: String) {
    Column(verticalArrangement = Arrangement.spacedBy(5.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(5.dp)) {
            Text(label, color = Ink300, style = MaterialTheme.typography.labelMedium); Icon(Icons.Default.Lock, null, tint = Ink500, modifier = Modifier.size(13.dp))
        }
        Surface(color = Ink950.copy(alpha = 0.72f), shape = RoundedCornerShape(12.dp), border = androidx.compose.foundation.BorderStroke(1.dp, Ink800)) {
            Text(value, Modifier.fillMaxWidth().padding(horizontal = 13.dp, vertical = 12.dp), color = Ink300, style = MaterialTheme.typography.bodyMedium)
        }
    }
}

private fun formatCacheBytes(bytes: Long): String = when {
    bytes >= 1024L * 1024L * 1024L -> "%.1f GB".format(bytes / (1024.0 * 1024.0 * 1024.0))
    bytes >= 1024L * 1024L -> "%.1f MB".format(bytes / (1024.0 * 1024.0))
    bytes >= 1024L -> "%.0f KB".format(bytes / 1024.0)
    else -> "$bytes B"
}
