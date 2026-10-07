package com.railguard360.app;

import android.Manifest;
import android.app.Activity;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.os.Bundle;
import android.view.Gravity;
import android.webkit.GeolocationPermissions;
import android.webkit.PermissionRequest;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.TextView;
import android.widget.Toast;

import java.net.URI;

public final class RailGuardActivity extends Activity {
    private static final int REQUEST_CAMERA = 1;
    private static final int REQUEST_LOCATION = 2;
    private static final String URL_KEY = "server_url";

    private LinearLayout root;
    private EditText addressInput;
    private PermissionRequest pendingCameraRequest;
    private GeolocationPermissions.Callback pendingLocationCallback;
    private String pendingLocationOrigin;

    @Override
    public void onCreate(Bundle state) {
        super.onCreate(state);
        getWindow().setStatusBarColor(Color.rgb(11, 17, 24));
        getWindow().setNavigationBarColor(Color.rgb(11, 17, 24));
        showAddressEntry(getPreferences(MODE_PRIVATE).getString(URL_KEY, ""));
    }

    private void showAddressEntry(String initialValue) {
        root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(dp(20), dp(32), dp(20), dp(20));
        root.setBackgroundColor(Color.rgb(7, 11, 16));

        TextView title = new TextView(this);
        title.setText("RAILGUARD 360");
        title.setTextColor(Color.WHITE);
        title.setTextSize(22);
        title.setGravity(Gravity.CENTER);
        root.addView(title, matchWrap());

        TextView note = new TextView(this);
        note.setText("Human body-pose fall/push detection. Enter the HTTPS address of your deployed RailGuard web server. Camera and location permission are requested when needed.");
        note.setTextColor(Color.LTGRAY);
        note.setTextSize(15);
        note.setPadding(0, dp(20), 0, dp(12));
        root.addView(note, matchWrap());

        addressInput = new EditText(this);
        addressInput.setSingleLine(true);
        addressInput.setTextColor(Color.WHITE);
        addressInput.setHintTextColor(Color.GRAY);
        addressInput.setHint("https://your-railguard-server.example");
        addressInput.setInputType(URI_INPUT_TYPE);
        addressInput.setText(initialValue);
        root.addView(addressInput, matchWrap());

        Button open = new Button(this);
        open.setText("Open monitoring app");
        open.setOnClickListener(view -> openServer());
        LinearLayout.LayoutParams buttonParams = matchWrap();
        buttonParams.topMargin = dp(12);
        root.addView(open, buttonParams);

        TextView safety = new TextView(this);
        safety.setText("HTTPS is required for camera/location access. Alerts need a reachable server and configured SMS gateway. This prototype is not railway-certified and cannot stop a train.");
        safety.setTextColor(Color.rgb(255, 183, 3));
        safety.setTextSize(13);
        safety.setPadding(0, dp(18), 0, 0);
        root.addView(safety, matchWrap());
        setContentView(root);
    }

    private static final int URI_INPUT_TYPE = 17;

    private void openServer() {
        String value = addressInput.getText().toString().trim();
        try {
            URI uri = URI.create(value);
            if (!"https".equalsIgnoreCase(uri.getScheme()) || uri.getHost() == null) {
                throw new IllegalArgumentException("Use a complete HTTPS URL.");
            }
            getPreferences(MODE_PRIVATE).edit().putString(URL_KEY, uri.toString()).apply();
            showWebView(uri.toString());
        } catch (IllegalArgumentException exception) {
            addressInput.setError("Enter a valid HTTPS server URL");
            Toast.makeText(this, "Use the full HTTPS address of your RailGuard server.", Toast.LENGTH_LONG).show();
        }
    }

    private void showWebView(String url) {
        WebView web = new WebView(this);
        WebSettings settings = web.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setGeolocationEnabled(true);
        settings.setMediaPlaybackRequiresUserGesture(false);

        web.setWebViewClient(new WebViewClient() {
            @Override
            public void onReceivedError(WebView view, WebResourceRequest request, WebResourceError error) {
                if (request.isForMainFrame()) {
                    Toast.makeText(RailGuardActivity.this, "Cannot load RailGuard server. Check the HTTPS address and network.", Toast.LENGTH_LONG).show();
                }
            }
        });

        web.setWebChromeClient(new WebChromeClient() {
            @Override
            public void onPermissionRequest(PermissionRequest request) {
                runOnUiThread(() -> {
                    boolean asksForCamera = false;
                    for (String resource : request.getResources()) {
                        if (PermissionRequest.RESOURCE_VIDEO_CAPTURE.equals(resource)) asksForCamera = true;
                    }
                    if (!asksForCamera) {
                        request.deny();
                    } else if (checkSelfPermission(Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED) {
                        request.grant(new String[]{PermissionRequest.RESOURCE_VIDEO_CAPTURE});
                    } else {
                        pendingCameraRequest = request;
                        requestPermissions(new String[]{Manifest.permission.CAMERA}, REQUEST_CAMERA);
                    }
                });
            }

            @Override
            public void onGeolocationPermissionsShowPrompt(String origin, GeolocationPermissions.Callback callback) {
                runOnUiThread(() -> {
                    if (hasLocationPermission()) {
                        callback.invoke(origin, true, false);
                    } else {
                        pendingLocationOrigin = origin;
                        pendingLocationCallback = callback;
                        requestPermissions(new String[]{
                                Manifest.permission.ACCESS_FINE_LOCATION,
                                Manifest.permission.ACCESS_COARSE_LOCATION
                        }, REQUEST_LOCATION);
                    }
                });
            }
        });

        root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundColor(Color.rgb(7, 11, 16));

        Button changeServer = new Button(this);
        changeServer.setText("Change server");
        changeServer.setOnClickListener(view -> showAddressEntry(getPreferences(MODE_PRIVATE).getString(URL_KEY, "")));
        root.addView(changeServer, matchWrap());
        root.addView(web, new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, 0, 1f));
        setContentView(root);
        web.loadUrl(url);
    }

    private boolean hasLocationPermission() {
        return checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED
                || checkSelfPermission(Manifest.permission.ACCESS_COARSE_LOCATION) == PackageManager.PERMISSION_GRANTED;
    }

    @Override
    public void onRequestPermissionsResult(int requestCode, String[] permissions, int[] results) {
        super.onRequestPermissionsResult(requestCode, permissions, results);
        if (requestCode == REQUEST_CAMERA && pendingCameraRequest != null) {
            if (results.length > 0 && results[0] == PackageManager.PERMISSION_GRANTED) {
                pendingCameraRequest.grant(new String[]{PermissionRequest.RESOURCE_VIDEO_CAPTURE});
            } else {
                pendingCameraRequest.deny();
            }
            pendingCameraRequest = null;
        } else if (requestCode == REQUEST_LOCATION && pendingLocationCallback != null) {
            boolean granted = hasLocationPermission();
            pendingLocationCallback.invoke(pendingLocationOrigin, granted, false);
            pendingLocationCallback = null;
            pendingLocationOrigin = null;
        }
    }

    private LinearLayout.LayoutParams matchWrap() {
        return new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT);
    }

    private int dp(int value) {
        return (int) (value * getResources().getDisplayMetrics().density + 0.5f);
    }
}
