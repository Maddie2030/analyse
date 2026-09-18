package com.mreader.android.ui.screens

import android.annotation.SuppressLint
import android.graphics.Bitmap
import android.net.Uri
import android.view.ViewGroup
import android.webkit.CookieManager
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.activity.compose.BackHandler
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.viewinterop.AndroidView
import androidx.compose.ui.unit.dp
import com.mreader.android.ui.AppViewModel
import com.mreader.android.ui.theme.Brand400
import com.mreader.android.ui.theme.Ink400
import com.mreader.android.ui.theme.Ink950

/**
 * Crash-safe chapter reader bridge.
 *
 * The public web reader is the server contract source of truth and is already
 * proven against the live image edge. The Android shell keeps discovery,
 * library, profile and notifications native, but delegates chapter rendering to
 * the exact working web reader until the native decoder path is fully proven on
 * real devices. Native session cookies are copied into the WebView before the
 * reader URL is loaded, so authenticated progress/comments continue to work.
 */
@SuppressLint("SetJavaScriptEnabled")
@Composable
fun WebReaderScreen(
    appViewModel: AppViewModel,
    seriesSlug: String,
    chapterSlug: String,
    onBack: () -> Unit,
) {
    val repository = appViewModel.repository
    val baseUrl = remember(repository.serverConfig().baseUrl) {
        repository.serverConfig().baseUrl.trimEnd('/')
    }
    val baseHost = remember(baseUrl) { Uri.parse(baseUrl).host.orEmpty() }
    val readerUrl = remember(baseUrl, seriesSlug, chapterSlug) {
        "$baseUrl/read/${Uri.encode(seriesSlug)}/${Uri.encode(chapterSlug)}"
    }

    var loading by remember(readerUrl) { mutableStateOf(true) }
    var error by remember(readerUrl) { mutableStateOf<String?>(null) }
    var webViewRef by remember { mutableStateOf<WebView?>(null) }

    BackHandler {
        val view = webViewRef
        if (view != null && view.canGoBack()) view.goBack() else onBack()
    }

    Box(Modifier.fillMaxSize().background(Ink950)) {
        AndroidView(
            modifier = Modifier.fillMaxSize(),
            factory = { context ->
                val cookieManager = CookieManager.getInstance().apply {
                    setAcceptCookie(true)
                }
                val sessionCookies = repository.api.webViewCookies()

                WebView(context).apply {
                    webViewRef = this
                    setBackgroundColor(android.graphics.Color.rgb(8, 8, 8))
                    layoutParams = ViewGroup.LayoutParams(
                        ViewGroup.LayoutParams.MATCH_PARENT,
                        ViewGroup.LayoutParams.MATCH_PARENT,
                    )
                    settings.apply {
                        javaScriptEnabled = true
                        domStorageEnabled = true
                        databaseEnabled = false
                        allowFileAccess = false
                        allowContentAccess = false
                        mixedContentMode = WebSettings.MIXED_CONTENT_NEVER_ALLOW
                        cacheMode = WebSettings.LOAD_DEFAULT
                        loadsImagesAutomatically = true
                        setSupportMultipleWindows(false)
                        userAgentString = "$userAgentString MReaderAndroid/${com.mreader.android.BuildConfig.VERSION_NAME}"
                    }
                    cookieManager.setAcceptThirdPartyCookies(this, false)
                    webViewClient = object : WebViewClient() {
                        override fun onPageStarted(view: WebView?, url: String?, favicon: Bitmap?) {
                            loading = true
                            error = null
                        }

                        override fun onPageFinished(view: WebView?, url: String?) {
                            loading = false
                        }

                        override fun onReceivedError(
                            view: WebView?,
                            request: WebResourceRequest?,
                            resourceError: WebResourceError?,
                        ) {
                            if (request?.isForMainFrame == true) {
                                loading = false
                                error = resourceError?.description?.toString()
                                    ?: "The web-compatible reader could not be loaded."
                            }
                        }

                        override fun onReceivedHttpError(
                            view: WebView?,
                            request: WebResourceRequest?,
                            errorResponse: WebResourceResponse?,
                        ) {
                            if (request?.isForMainFrame == true && (errorResponse?.statusCode ?: 0) >= 400) {
                                loading = false
                                error = "Reader route returned HTTP ${errorResponse?.statusCode ?: 0}."
                            }
                        }

                        override fun shouldOverrideUrlLoading(view: WebView?, request: WebResourceRequest?): Boolean {
                            val uri = request?.url ?: return false
                            if (!uri.host.equals(baseHost, ignoreCase = true)) return true
                            // When the web reader's back-to-series control is used,
                            // return to the native Series screen already below this
                            // route instead of trapping the user in a full web shell.
                            if (uri.path.orEmpty().startsWith("/series/")) {
                                onBack()
                                return true
                            }
                            return false
                        }
                    }

                    // CookieManager#setCookie is asynchronous on current Android
                    // WebView implementations. Chain the writes and only navigate
                    // after every native session cookie has been acknowledged so
                    // the first /read request cannot race ahead as an anonymous
                    // request. This keeps the embedded reader on the same session
                    // contract as the native Retrofit/OkHttp client.
                    fun loadAfterCookie(index: Int) {
                        if (index >= sessionCookies.size) {
                            cookieManager.flush()
                            post { loadUrl(readerUrl) }
                            return
                        }
                        cookieManager.setCookie(baseUrl, sessionCookies[index]) {
                            loadAfterCookie(index + 1)
                        }
                    }
                    loadAfterCookie(0)
                }
            },
            // Do not call loadUrl from AndroidView.update: the initial update can
            // run before asynchronous CookieManager writes finish and would race
            // the authenticated first navigation. Route changes recreate this
            // screen, while in-reader prev/next links stay inside the WebView.
            update = { },
        )

        if (loading) {
            CircularProgressIndicator(
                modifier = Modifier.align(Alignment.Center),
                color = Brand400,
            )
        }

        error?.let { message ->
            Column(
                modifier = Modifier.align(Alignment.Center).padding(horizontal = 28.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                Text("Reader connection failed", color = MaterialTheme.colorScheme.error)
                Text(message, color = Ink400, style = MaterialTheme.typography.bodySmall)
            }
        }
    }

    DisposableEffect(Unit) {
        onDispose {
            webViewRef?.apply {
                stopLoading()
                loadUrl("about:blank")
                clearHistory()
                removeAllViews()
                destroy()
            }
            webViewRef = null
        }
    }
}
