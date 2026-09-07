package com.khabardhun.publicapp;
import android.app.Activity; import android.os.Bundle; import android.webkit.WebView; import android.webkit.WebViewClient;
public class MainActivity extends Activity { public void onCreate(Bundle b){super.onCreate(b); WebView w=new WebView(this); w.setWebViewClient(new WebViewClient()); w.getSettings().setJavaScriptEnabled(true); w.loadUrl(getString(com.khabardhun.publicapp.R.string.backend_url)+"/app"); setContentView(w);} }
