package com.mreader.android.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
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
fun LoginScreen(
    appViewModel: AppViewModel,
    onDone: () -> Unit,
    onGuest: () -> Unit,
    onRegister: () -> Unit,
) {
    var identifier by rememberSaveable { mutableStateOf("") }
    var password by rememberSaveable { mutableStateOf("") }
    var busy by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    val scope = rememberCoroutineScope()

    Box(
        Modifier
            .fillMaxSize()
            .background(Brush.verticalGradient(listOf(Ink950, Ink950, Brand950.copy(alpha = 0.34f))))
            .safeDrawingPadding()
            .imePadding()
            .padding(20.dp),
        contentAlignment = Alignment.Center,
    ) {
        Column(
            Modifier.fillMaxWidth().widthIn(max = 480.dp).verticalScroll(rememberScrollState()),
            verticalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            MReaderBrand()
            Surface(
                color = Ink900,
                shape = RoundedCornerShape(22.dp),
                border = androidx.compose.foundation.BorderStroke(1.dp, Ink800),
            ) {
                Column(Modifier.padding(20.dp), verticalArrangement = Arrangement.spacedBy(14.dp)) {
                    Text("Welcome back", style = MaterialTheme.typography.headlineMedium, color = Ink50)
                    Text("Sign in to sync your library and reading progress.", color = Ink400)
                    OutlinedTextField(
                        value = identifier,
                        onValueChange = { identifier = it },
                        modifier = Modifier.fillMaxWidth(),
                        label = { Text("Username or email") },
                        leadingIcon = { Icon(Icons.Default.Person, null) },
                        singleLine = true,
                        shape = RoundedCornerShape(12.dp),
                        colors = OutlinedTextFieldDefaults.colors(
                            focusedBorderColor = Brand500,
                            unfocusedBorderColor = Ink700,
                            focusedContainerColor = Ink950,
                            unfocusedContainerColor = Ink950,
                        ),
                    )
                    OutlinedTextField(
                        value = password,
                        onValueChange = { password = it },
                        modifier = Modifier.fillMaxWidth(),
                        label = { Text("Password") },
                        leadingIcon = { Icon(Icons.Default.Lock, null) },
                        visualTransformation = PasswordVisualTransformation(),
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password),
                        singleLine = true,
                        shape = RoundedCornerShape(12.dp),
                        colors = OutlinedTextFieldDefaults.colors(
                            focusedBorderColor = Brand500,
                            unfocusedBorderColor = Ink700,
                            focusedContainerColor = Ink950,
                            unfocusedContainerColor = Ink950,
                        ),
                    )
                    error?.let {
                        Surface(color = Brand950.copy(alpha = 0.55f), shape = RoundedCornerShape(10.dp)) {
                            Text(it, Modifier.padding(10.dp), color = Brand100, style = MaterialTheme.typography.bodySmall)
                        }
                    }
                    Button(
                        onClick = {
                            if (busy) return@Button
                            busy = true
                            error = null
                            scope.launch {
                                val result = appViewModel.login(identifier, password)
                                busy = false
                                result.onSuccess { onDone() }.onFailure { error = it.message ?: "Login failed." }
                            }
                        },
                        modifier = Modifier.fillMaxWidth(),
                        enabled = identifier.isNotBlank() && password.isNotBlank() && !busy,
                        colors = ButtonDefaults.buttonColors(containerColor = Brand600),
                        shape = RoundedCornerShape(12.dp),
                    ) { Text(if (busy) "Signing in…" else "Sign in") }
                    TextButton(onClick = onRegister, modifier = Modifier.align(Alignment.CenterHorizontally)) {
                        Text("Don’t have an account? Create one", color = Brand300)
                    }
                    TextButton(onClick = onGuest, modifier = Modifier.align(Alignment.CenterHorizontally)) {
                        Text("Continue as guest", color = Ink300)
                    }
                }
            }
        }
    }
}
