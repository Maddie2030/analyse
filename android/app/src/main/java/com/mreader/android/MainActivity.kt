package com.mreader.android

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.viewModels
import com.mreader.android.ui.AppViewModel
import com.mreader.android.ui.MReaderApp
import com.mreader.android.ui.theme.MReaderTheme

class MainActivity : ComponentActivity() {
    private val appViewModel: AppViewModel by viewModels {
        AppViewModel.Factory((application as MReaderApplication).repository)
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
            MReaderTheme {
                MReaderApp(appViewModel)
            }
        }
    }
}
