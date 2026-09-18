plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.plugin.compose")
}

android {
    namespace = "com.mreader.android"
    compileSdk = 36

    defaultConfig {
        applicationId = "com.mreader.android"
        minSdk = 26
        targetSdk = 36
        versionCode = 484
        versionName = "ver.1.1.0"

        val configuredBaseUrl = providers.gradleProperty("MREADER_BASE_URL")
            .orElse("https://overlord.seahorse-banded.ts.net")
            .get()
            .trimEnd('/')
        buildConfigField("String", "MREADER_DEFAULT_BASE_URL", "\"$configuredBaseUrl\"")

        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
    }

    buildTypes {
        debug {
            applicationIdSuffix = ".debug"
        }
        release {
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro",
            )
        }
    }

    buildFeatures {
        compose = true
        buildConfig = true
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    packaging {
        resources.excludes += setOf(
            "/META-INF/{AL2.0,LGPL2.1}",
            "/META-INF/LICENSE*",
            "/META-INF/NOTICE*",
        )
    }
}

dependencies {
    // Keep the UI stack on the last stable compileSdk-36-compatible lines.
    // Compose 1.12+, Lifecycle 2.11 Compose artifacts, and Navigation 2.10 require compileSdk 37.
    val composeBom = platform("androidx.compose:compose-bom:2026.06.01")
    implementation(composeBom)
    androidTestImplementation(composeBom)

    implementation("androidx.activity:activity-compose:1.13.0")
    implementation("androidx.lifecycle:lifecycle-runtime-compose:2.10.0")
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.10.0")
    implementation("androidx.navigation:navigation-compose:2.9.8")

    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.material:material-icons-extended")
    implementation("androidx.compose.foundation:foundation")
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.ui:ui-tooling-preview")
    debugImplementation("androidx.compose.ui:ui-tooling")

    implementation(platform("com.squareup.okhttp3:okhttp-bom:5.4.0"))
    implementation("com.squareup.okhttp3:okhttp")
    // Retrofit provides one declarative, auditable API contract over OkHttp.
    implementation("com.squareup.retrofit2:retrofit:3.0.0")

    testImplementation("junit:junit:4.13.2")
}
