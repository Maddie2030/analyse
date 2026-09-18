package com.mreader.android.core.repository

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ReaderVariantPolicyTest {
    @Test fun normalDprPhoneUsesResponsiveDerivative() {
        assertTrue(ReaderVariantPolicy.preferResponsive(360, 720f, 720))
    }

    @Test fun highDprPhoneKeepsPrimaryAsset() {
        assertFalse(ReaderVariantPolicy.preferResponsive(412, 1236f, 720))
    }

    @Test fun wideLayoutKeepsPrimaryAsset() {
        assertFalse(ReaderVariantPolicy.preferResponsive(900, 900f, 1080))
    }

    @Test fun missingResponsiveMetadataKeepsPrimaryAsset() {
        assertFalse(ReaderVariantPolicy.preferResponsive(360, 720f, null))
    }
}
