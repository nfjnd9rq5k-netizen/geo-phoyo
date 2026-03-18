// ============================================================
//  SSL BYPASS — Bypass certificate pinning (5 couches)
// ============================================================

function initSSLBypass() {
    if (!CONFIG.ssl.enabled) {
        log("SSL", "SSL bypass desactive dans config");
        return;
    }

    // Couche 1 : OkHttp3 CertificatePinner
    try {
        var CertificatePinner = Java.use("okhttp3.CertificatePinner");
        CertificatePinner.check.overload(
            "java.lang.String", "java.util.List"
        ).implementation = function (hostname, peerCertificates) {
            log("SSL", "OkHttp3 CertificatePinner.check(" + hostname + ") -> bypass");
            return;
        };

        // Aussi l'overload avec varargs
        try {
            CertificatePinner.check.overload(
                "java.lang.String", "[Ljava.security.cert.Certificate;"
            ).implementation = function (hostname, peerCertificates) {
                log("SSL", "OkHttp3 CertificatePinner.check(varargs) -> bypass");
                return;
            };
        } catch (e) {}

        log("SSL", "OkHttp3 CertificatePinner bypass installe");
    } catch (e) {
        log("SSL", "OkHttp3 non trouve, skip");
    }

    // Couche 2 : TrustManagerImpl (Conscrypt) — verifyChain
    try {
        var TrustManagerImpl = Java.use("com.android.org.conscrypt.TrustManagerImpl");
        TrustManagerImpl.verifyChain.implementation = function (untrustedChain, trustAnchorChain, host, clientAuth, ocspData, tlsSctData) {
            log("SSL", "TrustManagerImpl.verifyChain(" + host + ") -> bypass");
            return untrustedChain;
        };
        log("SSL", "TrustManagerImpl (Conscrypt) bypass installe");
    } catch (e) {
        log("SSL", "TrustManagerImpl non trouve, skip");
    }

    // Couche 3 : SSLContext.init() — injecter TrustManager permissif
    try {
        var X509TrustManager = Java.use("javax.net.ssl.X509TrustManager");
        var SSLContext = Java.use("javax.net.ssl.SSLContext");

        var TrustAllManager = Java.registerClass({
            name: "com.frida.TrustAllManager",
            implements: [X509TrustManager],
            methods: {
                checkClientTrusted: function (chain, authType) {},
                checkServerTrusted: function (chain, authType) {},
                getAcceptedIssuers: function () {
                    return [];
                }
            }
        });

        SSLContext.init.implementation = function (keyManagers, trustManagers, secureRandom) {
            log("SSL", "SSLContext.init() -> injection TrustAllManager");
            var trustAllArray = Java.array("javax.net.ssl.TrustManager", [TrustAllManager.$new()]);
            this.init(keyManagers, trustAllArray, secureRandom);
        };

        log("SSL", "SSLContext.init bypass installe");
    } catch (e) {
        log("SSL", "SSLContext.init hook erreur: " + e);
    }

    // Couche 4 : NetworkSecurityTrustManager (Android 7+)
    try {
        var NetworkSecurityTrustManager = Java.use("android.security.net.config.NetworkSecurityTrustManager");
        NetworkSecurityTrustManager.checkServerTrusted.overload(
            "[Ljava.security.cert.X509Certificate;", "java.lang.String"
        ).implementation = function (chain, authType) {
            log("SSL", "NetworkSecurityTrustManager.checkServerTrusted -> bypass");
            return;
        };
        log("SSL", "NetworkSecurityTrustManager bypass installe");
    } catch (e) {
        log("SSL", "NetworkSecurityTrustManager non trouve, skip");
    }

    // Couche 5 : Flutter ssl_crypto_x509_session_verify_cert_chain
    try {
        if (typeof Module.findBaseAddress !== "function") {
            log("SSL", "Flutter bypass skip — Module.findBaseAddress indisponible");
        } else {
            var flutter_lib = Module.findBaseAddress("libflutter.so");
            if (flutter_lib !== null) {
                var symbols = Module.enumerateExportsSync("libflutter.so");
                for (var i = 0; i < symbols.length; i++) {
                    if (symbols[i].name.indexOf("ssl_crypto_x509_session_verify_cert_chain") !== -1) {
                        Interceptor.attach(symbols[i].address, {
                            onLeave: function (retval) {
                                retval.replace(0x1);
                                log("SSL", "Flutter cert verify -> bypass");
                            }
                        });
                        log("SSL", "Flutter SSL bypass installe");
                        break;
                    }
                }
            }
        }
    } catch (e) {
        log("SSL", "Flutter non detecte, skip: " + e);
    }

    log("SSL", "=== SSL bypass actif ===");
}
