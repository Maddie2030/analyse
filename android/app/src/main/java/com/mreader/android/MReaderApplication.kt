package com.mreader.android

import android.app.Application
import com.mreader.android.core.repository.MReaderRepository

class MReaderApplication : Application() {
    lateinit var repository: MReaderRepository
        private set

    override fun onCreate() {
        super.onCreate()
        repository = MReaderRepository(this)
    }
}
