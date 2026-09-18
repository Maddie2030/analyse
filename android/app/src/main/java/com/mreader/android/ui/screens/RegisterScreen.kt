package com.mreader.android.ui.screens

import android.util.Patterns
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Email
import androidx.compose.material.icons.filled.Lock
import androidx.compose.material.icons.filled.Person
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import com.mreader.android.ui.AppViewModel
import com.mreader.android.ui.components.MReaderBrand
import com.mreader.android.ui.theme.*
import kotlinx.coroutines.launch

@Composable
fun RegisterScreen(appViewModel: AppViewModel, onDone: () -> Unit, onLogin: () -> Unit) {
    var username by rememberSaveable { mutableStateOf("") }
    var email by rememberSaveable { mutableStateOf("") }
    var password by rememberSaveable { mutableStateOf("") }
    var busy by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    val scope = rememberCoroutineScope()
    val valid = username.trim().length >= 3 && Patterns.EMAIL_ADDRESS.matcher(email.trim()).matches() && password.length >= 8

    Box(
        Modifier.fillMaxSize().background(Brush.verticalGradient(listOf(Ink950, Ink950, Brand950.copy(alpha = .34f)))).safeDrawingPadding().imePadding().padding(20.dp),
        contentAlignment = Alignment.Center,
    ) {
        Column(Modifier.fillMaxWidth().widthIn(max = 480.dp).verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(16.dp)) {
            MReaderBrand()
            Surface(color = Ink900, shape = RoundedCornerShape(22.dp), border = androidx.compose.foundation.BorderStroke(1.dp, Ink800)) {
                Column(Modifier.padding(20.dp), verticalArrangement = Arrangement.spacedBy(14.dp)) {
                    Text("Create account", style = MaterialTheme.typography.headlineMedium, color = Ink50)
                    Text("Keep your library, follows, ratings and reading position in sync with the web application.", color = Ink400)
                    WebAuthField(username, { username = it.take(40) }, "Username", Icons.Default.Person, KeyboardType.Text, false)
                    WebAuthField(email, { email = it.take(160) }, "Email", Icons.Default.Email, KeyboardType.Email, false)
                    WebAuthField(password, { password = it.take(128) }, "Password", Icons.Default.Lock, KeyboardType.Password, true)
                    Text("Use at least 8 characters. Server-side validation remains authoritative.", color = Ink500, style = MaterialTheme.typography.labelSmall)
                    error?.let { Surface(color = Brand950.copy(alpha = .55f), shape = RoundedCornerShape(10.dp)) { Text(it, Modifier.padding(10.dp), color = Brand100, style = MaterialTheme.typography.bodySmall) } }
                    Button(
                        onClick = {
                            if (busy || !valid) return@Button
                            busy = true; error = null
                            scope.launch {
                                val result = appViewModel.register(username, email, password)
                                busy = false
                                result.onSuccess { onDone() }.onFailure { error = it.message ?: "Registration failed." }
                            }
                        },
                        enabled = valid && !busy,
                        modifier = Modifier.fillMaxWidth(),
                        colors = ButtonDefaults.buttonColors(containerColor = Brand600),
                        shape = RoundedCornerShape(12.dp),
                    ) { Text(if (busy) "Creating account…" else "Create account") }
                    TextButton(onClick = onLogin, modifier = Modifier.align(Alignment.CenterHorizontally)) { Text("Already have an account? Sign in", color = Brand300) }
                }
            }
        }
    }
}

@Composable
private fun WebAuthField(
    value: String,
    onValueChange: (String) -> Unit,
    label: String,
    icon: androidx.compose.ui.graphics.vector.ImageVector,
    keyboardType: KeyboardType,
    password: Boolean,
) {
    OutlinedTextField(
        value = value,
        onValueChange = onValueChange,
        modifier = Modifier.fillMaxWidth(),
        label = { Text(label) },
        leadingIcon = { Icon(icon, null) },
        visualTransformation = if (password) PasswordVisualTransformation() else androidx.compose.ui.text.input.VisualTransformation.None,
        keyboardOptions = KeyboardOptions(keyboardType = keyboardType),
        singleLine = true,
        shape = RoundedCornerShape(12.dp),
        colors = OutlinedTextFieldDefaults.colors(focusedBorderColor = Brand500, unfocusedBorderColor = Ink700, focusedContainerColor = Ink950, unfocusedContainerColor = Ink950),
    )
}
