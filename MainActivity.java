package com.khabardhun.owner;

import android.Manifest;
import android.app.*;
import android.content.*;
import android.content.pm.PackageManager;
import android.media.RingtoneManager;
import android.net.Uri;
import android.os.*;
import android.speech.tts.TextToSpeech;
import android.webkit.*;
import androidx.core.app.NotificationCompat;
import androidx.core.app.NotificationManagerCompat;
import java.io.*;
import java.net.*;
import java.util.*;
import java.util.regex.*;

public class MainActivity extends Activity {
    WebView w; Handler h=new Handler(Looper.getMainLooper()); TextToSpeech tts; String last="0";
    static final String CH="kd_red_alert";
    public void onCreate(Bundle b){super.onCreate(b);
        if(Build.VERSION.SDK_INT>=33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS)!=PackageManager.PERMISSION_GRANTED) requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS},77);
        NotificationManager nm=getSystemService(NotificationManager.class); if(Build.VERSION.SDK_INT>=26) nm.createNotificationChannel(new NotificationChannel(CH,"KHABAR DHUN Red Alerts",NotificationManager.IMPORTANCE_HIGH));
        tts=new TextToSpeech(this, s->{if(s==TextToSpeech.SUCCESS) tts.setLanguage(new Locale("hi","IN"));});
        w=new WebView(this); w.setWebViewClient(new WebViewClient()); w.getSettings().setJavaScriptEnabled(true); w.getSettings().setDomStorageEnabled(true);
        w.loadUrl(getString(com.khabardhun.owner.R.string.backend_url)+"/"); setContentView(w);
        h.postDelayed(new Runnable(){public void run(){pollAlerts();h.postDelayed(this,7000);}},7000);
    }
    void pollAlerts(){new Thread(()->{try{String base=getString(com.khabardhun.owner.R.string.backend_url); String cookie=CookieManager.getInstance().getCookie(base); HttpURLConnection c=(HttpURLConnection)new URL(base+"/api/alerts/open").openConnection(); if(cookie!=null)c.setRequestProperty("Cookie",cookie); c.setRequestProperty("Accept","application/json"); c.setConnectTimeout(4000); c.setReadTimeout(4000); BufferedReader r=new BufferedReader(new InputStreamReader(c.getInputStream())); StringBuilder b=new StringBuilder();String line;while((line=r.readLine())!=null)b.append(line);r.close(); Matcher idm=Pattern.compile("\\"id\\"\\s*:\\s*(\\d+)").matcher(b.toString()); Matcher tm=Pattern.compile("\\"title\\"\\s*:\\s*\\"(.*?)\\"").matcher(b.toString()); Matcher mm=Pattern.compile("\\"message\\"\\s*:\\s*\\"(.*?)\\"").matcher(b.toString()); if(idm.find()&&tm.find()){String id=idm.group(1);if(!id.equals(last)){last=id;String title=tm.group(1);String msg=mm.find()?mm.group(1):"";h.post(()->notifyAlert(title,msg));}}}catch(Exception ignored){}}).start();}
    void notifyAlert(String title,String msg){Uri sound=RingtoneManager.getDefaultUri(RingtoneManager.TYPE_ALARM); Notification n=new NotificationCompat.Builder(this,CH).setSmallIcon(android.R.drawable.ic_dialog_alert).setContentTitle("🔴 KHABAR DHUN RED ALERT").setContentText(title).setStyle(new NotificationCompat.BigTextStyle().bigText(msg)).setPriority(NotificationCompat.PRIORITY_MAX).setSound(sound).setVibrate(new long[]{0,500,300,500,300,900}).setAutoCancel(true).build(); if(Build.VERSION.SDK_INT<33||checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS)==PackageManager.PERMISSION_GRANTED) NotificationManagerCompat.from(this).notify(9001,n); if(tts!=null)tts.speak("ध्यान दें। आपके न्यूज़रूम में महत्वपूर्ण खबर आई है। "+title+"। "+msg,TextToSpeech.QUEUE_FLUSH,null,"kdalert");}
    protected void onDestroy(){if(tts!=null)tts.shutdown();super.onDestroy();}
}
