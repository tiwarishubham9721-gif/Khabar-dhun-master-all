package com.khabardhun.publicapp;

import android.app.Activity;
import android.os.Bundle;
import android.content.Intent;
import android.net.Uri;
import android.graphics.Color;
import android.view.Gravity;
import android.view.ViewGroup;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.TextView;

public class MainActivity extends Activity {
    WebView web;
    String base(){ return BuildConfig.BACKEND_URL.replaceAll("/$", ""); }
    @Override public void onCreate(Bundle b){ super.onCreate(b);
        LinearLayout root=new LinearLayout(this); root.setOrientation(LinearLayout.VERTICAL); root.setBackgroundColor(Color.rgb(7,16,29));
        LinearLayout bar=new LinearLayout(this); bar.setPadding(12,8,12,8); bar.setGravity(Gravity.CENTER_VERTICAL); bar.setBackgroundColor(Color.rgb(9,21,35));
        TextView title=new TextView(this); title.setText("KHABAR DHUN"); title.setTextColor(Color.WHITE); title.setTextSize(18); title.setTypeface(null,1);
        bar.addView(title,new LinearLayout.LayoutParams(0,56,1));
        Button refer=new Button(this); refer.setText("Referral"); refer.setOnClickListener(v->web.loadUrl(base()+"/referral")); bar.addView(refer,new LinearLayout.LayoutParams(-2,56));
        Button share=new Button(this); share.setText("Share"); share.setOnClickListener(v->{ Intent i=new Intent(Intent.ACTION_SEND); i.setType("text/plain"); i.putExtra(Intent.EXTRA_TEXT,base()+"/referral"); startActivity(Intent.createChooser(i,"KHABAR DHUN Referral Share")); }); bar.addView(share,new LinearLayout.LayoutParams(-2,56));
        root.addView(bar,new LinearLayout.LayoutParams(-1,64));
        web=new WebView(this); web.setWebViewClient(new WebViewClient()); web.getSettings().setJavaScriptEnabled(true); web.getSettings().setDomStorageEnabled(true); web.getSettings().setMediaPlaybackRequiresUserGesture(false); web.loadUrl(base()+"/app"); root.addView(web,new LinearLayout.LayoutParams(-1,0,1));
        setContentView(root);
    }
}
