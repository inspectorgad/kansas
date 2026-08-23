plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
    alias(libs.plugins.kotlin.compose)
    alias(libs.plugins.kotlin.serialization)
}

android {
    namespace = "org.ksrace.senate2026"
    compileSdk = 35

    defaultConfig {
        applicationId = "org.ksrace.senate2026"
        minSdk = 26
        targetSdk = 35
        versionCode = 1
        versionName = "0.1.0"
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"

        // Where the collector publishes. Overridable so a fork can point the app
        // at its own data branch without touching code.
        buildConfigField(
            "String",
            "DATA_BASE_URL",
            "\"${project.findProperty("dataBaseUrl") ?: "https://raw.githubusercontent.com/inspectorgad/kansas/data/data/"}\"",
        )

        // Which build this is. Every CI artifact is uploaded under the same name,
        // so without this there is no way to tell a freshly installed APK from
        // one built hours earlier — and the symptom of running an old one is a
        // feature simply not appearing, which reads exactly like a broken feature.
        // Surfaced under Settings > About.
        buildConfigField(
            "String",
            "GIT_SHA",
            "\"${(System.getenv("GITHUB_SHA") ?: "local").take(7)}\"",
        )
    }

    // A checked-in debug key, so every CI build is signed the same way.
    //
    // Without this, Gradle falls back to ~/.android/debug.keystore, which does not
    // exist on a fresh CI runner and is generated with a new random key on every
    // run. Each artifact was therefore signed differently, and installing one over
    // another failed with INSTALL_FAILED_UPDATE_INCOMPATIBLE — a full uninstall,
    // losing cached data and settings, for every build.
    //
    // This key secures nothing and is not meant to. It carries the conventional
    // debug credentials, so anyone with the repository can build an APK that
    // installs over this one; that is the accepted cost of being able to sideload
    // successive builds, and it is why release signing is deliberately kept out of
    // it. Never point the release type at this config.
    signingConfigs {
        getByName("debug") {
            storeFile = rootProject.file("debug.keystore")
            storePassword = "android"
            keyAlias = "androiddebugkey"
            keyPassword = "android"
        }
    }

    buildTypes {
        debug {
            applicationIdSuffix = ".debug"
            signingConfig = signingConfigs.getByName("debug")
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

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlin {
        compilerOptions {
            jvmTarget.set(org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17)
        }
    }

    buildFeatures {
        compose = true
        buildConfig = true
    }

    packaging {
        resources.excludes += "/META-INF/{AL2.0,LGPL2.1}"
    }

    lint {
        warningsAsErrors = false
        abortOnError = true
        disable += setOf("GradleDependency", "NewerVersionAvailable", "ObsoleteLintCustomCheck")
    }

    testOptions {
        unitTests.isReturnDefaultValues = true
    }
}

dependencies {
    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.lifecycle.runtime.ktx)
    implementation(libs.androidx.lifecycle.runtime.compose)
    implementation(libs.androidx.lifecycle.viewmodel.compose)
    implementation(libs.androidx.activity.compose)

    implementation(platform(libs.androidx.compose.bom))
    implementation(libs.androidx.compose.ui)
    implementation(libs.androidx.compose.ui.graphics)
    implementation(libs.androidx.compose.ui.tooling.preview)
    implementation(libs.androidx.compose.material3)
    implementation(libs.androidx.compose.material.icons.extended)
    debugImplementation(libs.androidx.compose.ui.tooling)

    implementation(libs.androidx.work.runtime.ktx)
    implementation(libs.kotlinx.serialization.json)
    implementation(libs.kotlinx.coroutines.android)
    implementation(libs.okhttp)

    testImplementation(libs.junit)
    testImplementation(libs.kotlinx.coroutines.test)
    testImplementation(libs.okhttp.mockwebserver)

    androidTestImplementation(libs.androidx.junit)
    androidTestImplementation(libs.androidx.espresso.core)
}
