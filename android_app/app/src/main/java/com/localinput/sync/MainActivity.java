package com.localinput.sync;

import android.Manifest;
import android.app.Activity;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.database.Cursor;
import android.graphics.Color;
import android.graphics.drawable.GradientDrawable;
import android.net.Uri;
import android.os.Bundle;
import android.provider.OpenableColumns;
import android.speech.RecognizerIntent;
import android.text.Editable;
import android.text.InputType;
import android.text.TextWatcher;
import android.util.AttributeSet;
import android.view.Gravity;
import android.view.KeyEvent;
import android.view.MotionEvent;
import android.view.View;
import android.view.WindowManager;
import android.view.inputmethod.EditorInfo;
import android.view.inputmethod.InputConnection;
import android.view.inputmethod.InputConnectionWrapper;
import android.view.inputmethod.InputMethodManager;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.Toast;

import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.DatagramPacket;
import java.net.DatagramSocket;
import java.net.HttpURLConnection;
import java.net.InetAddress;
import java.net.SocketTimeoutException;
import java.net.URL;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Locale;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicInteger;

public class MainActivity extends Activity {
    private static final String DEFAULT_BASE_URL = "http://192.168.20.75:8787";
    private static final String DEFAULT_MOUSE_HOST = "192.168.20.75";
    private static final String DEFAULT_KEY = "";
    private static final String PREFS_NAME = "connection";
    private static final String PREF_BASE_URL = "base_url";
    private static final String PREF_MOUSE_HOST = "mouse_host";
    private static final String PREF_KEY = "key";
    private static final String DISCOVERY_MESSAGE = "{\"discover\":\"phone_input_sync\"}";
    private static final int MOUSE_PORT = 8787;
    private static final int REQUEST_PICK_IMAGE = 42;
    private static final int REQUEST_VOICE_INPUT = 43;
    private static final int REQUEST_RECORD_AUDIO = 44;
    private static final int MAX_IMAGE_BYTES = 50 * 1024 * 1024;
    private static final long LOCAL_EDIT_PROTECT_MS = 900;

    private final ExecutorService network = Executors.newSingleThreadExecutor();
    private final ExecutorService mouseNetwork = Executors.newSingleThreadExecutor();
    private final ExecutorService snapshotNetwork = Executors.newSingleThreadExecutor();
    private final ExecutorService discoveryNetwork = Executors.newSingleThreadExecutor();
    private final Object mouseLock = new Object();
    private final AtomicBoolean mouseFlushScheduled = new AtomicBoolean(false);
    private final AtomicBoolean mouseRequestInFlight = new AtomicBoolean(false);
    private final AtomicInteger syncRevision = new AtomicInteger(0);
    private float pendingMouseDx = 0f;
    private float pendingMouseDy = 0f;
    private float pendingWheelX = 0f;
    private float pendingWheelY = 0f;
    private float mouseRemainderDx = 0f;
    private float mouseRemainderDy = 0f;
    private float wheelRemainderX = 0f;
    private float wheelRemainderY = 0f;
    private DatagramSocket mouseSocket;
    private InetAddress mouseAddress;
    private SyncEditText input;
    private View computerDot;
    private View inputDot;
    private View syncDot;
    private String baseUrl = DEFAULT_BASE_URL;
    private String mouseHost = DEFAULT_MOUSE_HOST;
    private String accessKey = DEFAULT_KEY;
    private String previous = "";
    private boolean suppressChange = false;
    private long lastSnapshotRequestMs = 0L;
    private long lastLocalEditMs = 0L;
    private volatile boolean running = true;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        getWindow().setSoftInputMode(WindowManager.LayoutParams.SOFT_INPUT_STATE_ALWAYS_VISIBLE);
        loadConnectionConfig();

        input = new SyncEditText(this);
        input.setSendListener(this::sendAndClear);
        input.setRemoteDeleteListener(() -> postSync(1, "", 0, false, input.getText().toString()));
        input.setPhotoPickerListener(this::openPhotoPicker);
        input.setTouchpadListener((dx, dy, wheelX, wheelY, action) -> postMouse(dx, dy, wheelX, wheelY, action));
        input.setBackgroundColor(Color.WHITE);
        input.setTextColor(Color.rgb(17, 17, 17));
        input.setTextSize(22);
        input.setGravity(Gravity.TOP | Gravity.START);
        input.setPadding(22, 22, 22, 22);
        input.setSingleLine(false);
        input.setHorizontallyScrolling(false);
        input.setMinLines(12);
        input.setImeOptions(EditorInfo.IME_ACTION_SEND | EditorInfo.IME_FLAG_NO_EXTRACT_UI);
        input.setRawInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_FLAG_CAP_SENTENCES);
        setContentView(buildAppLayout());

        input.addTextChangedListener(new TextWatcher() {
            @Override
            public void beforeTextChanged(CharSequence s, int start, int count, int after) {
            }

            @Override
            public void onTextChanged(CharSequence s, int start, int before, int count) {
            }

            @Override
            public void afterTextChanged(Editable editable) {
                if (suppressChange) {
                    return;
                }
                String current = editable.toString();
                SyncOp op = diff(previous, current);
                previous = current;
                if (op.deleteCount > 0 || !op.insertText.isEmpty()) {
                    lastLocalEditMs = System.currentTimeMillis();
                    postSync(op.deleteCount, op.insertText, op.suffixCount, false, current);
                }
            }
        });

        input.setOnEditorActionListener((view, actionId, event) -> handleEditorAction(actionId, event));
        input.setOnKeyListener((view, keyCode, event) -> {
            if (keyCode == KeyEvent.KEYCODE_ENTER && event.getAction() == KeyEvent.ACTION_UP) {
                sendAndClear();
                return true;
            }
            return false;
        });
        input.setOnClickListener(view -> wakeKeyboard());
        startFocusEvents();
        discoverDesktopService();
        handleIncomingImage(getIntent());
        showFlash("正在连接电脑...");
        fetchSnapshot();
        forceWakeKeyboard();
    }

    private View buildAppLayout() {
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundColor(Color.WHITE);

        LinearLayout statusRow = new LinearLayout(this);
        statusRow.setOrientation(LinearLayout.HORIZONTAL);
        statusRow.setGravity(Gravity.START | Gravity.CENTER_VERTICAL);
        statusRow.setPadding(dp(10), dp(4), 0, dp(2));
        statusRow.setBackgroundColor(Color.WHITE);

        LinearLayout statusPill = new LinearLayout(this);
        statusPill.setOrientation(LinearLayout.HORIZONTAL);
        statusPill.setGravity(Gravity.CENTER);
        statusPill.setPadding(0, 0, 0, 0);

        computerDot = createStatusDot();
        inputDot = createStatusDot();
        syncDot = createStatusDot();
        statusPill.addView(computerDot);
        statusPill.addView(inputDot);
        statusPill.addView(syncDot);
        statusRow.addView(statusPill, new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.WRAP_CONTENT,
                dp(12)
        ));
        setDot(computerDot, false);
        setDot(inputDot, false);
        setDot(syncDot, false);

        Button syncButton = new Button(this);
        syncButton.setAllCaps(false);
        syncButton.setText("同步电脑输入框");
        syncButton.setTextSize(16);
        syncButton.setTextColor(Color.rgb(20, 20, 20));
        syncButton.setBackgroundColor(Color.rgb(245, 245, 245));
        syncButton.setOnClickListener(view -> {
            showFlash("正在读取电脑输入框...");
            fetchSnapshot(true);
            wakeKeyboard();
        });

        root.addView(statusRow, new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                dp(24)
        ));
        root.addView(input, new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                0,
                1f
        ));
        root.addView(syncButton, new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                dp(52)
        ));
        return root;
    }

    private View createStatusDot() {
        View bar = new View(this);
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(dp(18), dp(3));
        params.setMargins(0, 0, dp(5), 0);
        bar.setLayoutParams(params);
        return bar;
    }

    private void setDot(View dot, boolean ok) {
        if (dot == null) {
            return;
        }
        GradientDrawable bg = new GradientDrawable();
        bg.setShape(GradientDrawable.RECTANGLE);
        bg.setCornerRadius(dp(2));
        bg.setColor(ok ? Color.rgb(0, 230, 118) : Color.rgb(214, 218, 222));
        dot.setBackground(bg);
    }

    private void setInputDotWaiting() {
        if (inputDot == null) {
            return;
        }
        setDot(inputDot, false);
    }

    private void showFlash(String message) {
        Toast.makeText(this, message, Toast.LENGTH_SHORT).show();
    }

    private int dp(int value) {
        return Math.round(value * getResources().getDisplayMetrics().density);
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        setIntent(intent);
        handleIncomingImage(intent);
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode == REQUEST_PICK_IMAGE && resultCode == RESULT_OK && data != null && data.getData() != null) {
            uploadImage(data.getData());
        }
        if (requestCode == REQUEST_VOICE_INPUT && resultCode == RESULT_OK && data != null) {
            ArrayList<String> results = data.getStringArrayListExtra(RecognizerIntent.EXTRA_RESULTS);
            if (results != null && !results.isEmpty()) {
                insertVoiceText(results.get(0));
            }
        }
    }

    @Override
    public void onRequestPermissionsResult(int requestCode, String[] permissions, int[] grantResults) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
        if (requestCode == REQUEST_RECORD_AUDIO) {
            if (grantResults.length > 0 && grantResults[0] == PackageManager.PERMISSION_GRANTED) {
                launchVoiceRecognizer();
            } else {
                showFlash("需要允许麦克风权限");
                wakeKeyboard();
            }
        }
    }

    @Override
    protected void onResume() {
        super.onResume();
        fetchSnapshot();
        forceWakeKeyboard();
    }

    @Override
    protected void onDestroy() {
        running = false;
        network.shutdownNow();
        mouseNetwork.shutdownNow();
        snapshotNetwork.shutdownNow();
        discoveryNetwork.shutdownNow();
        if (mouseSocket != null) {
            mouseSocket.close();
        }
        super.onDestroy();
    }

    private void clearLocalText() {
        suppressChange = true;
        input.setText("");
        previous = "";
        suppressChange = false;
    }

    private void applySnapshotText(String text) {
        suppressChange = true;
        input.setText(text);
        input.setSelection(input.getText().length());
        previous = text;
        suppressChange = false;
    }

    private boolean handleEditorAction(int actionId, KeyEvent event) {
        boolean isSendAction = actionId == EditorInfo.IME_ACTION_SEND
                || actionId == EditorInfo.IME_ACTION_DONE
                || actionId == EditorInfo.IME_ACTION_GO;
        boolean isEnterUp = event != null
                && event.getKeyCode() == KeyEvent.KEYCODE_ENTER
                && event.getAction() == KeyEvent.ACTION_UP;
        if (isSendAction || isEnterUp) {
            sendAndClear();
            return true;
        }
        return false;
    }

    private void sendAndClear() {
        postSync(0, "", 0, true, "");
        clearLocalText();
        showFlash("已发送");
        wakeKeyboard();
    }

    private void wakeKeyboard() {
        input.requestFocus();
        input.postDelayed(() -> {
            input.setSelection(input.getText().length());
            InputMethodManager imm = (InputMethodManager) getSystemService(Context.INPUT_METHOD_SERVICE);
            if (imm != null) {
                imm.showSoftInput(input, InputMethodManager.SHOW_FORCED);
            }
        }, 80);
    }

    private void forceWakeKeyboard() {
        input.requestFocus();
        input.postDelayed(this::wakeKeyboard, 80);
        input.postDelayed(this::wakeKeyboard, 220);
        input.postDelayed(this::wakeKeyboard, 520);
        input.postDelayed(this::wakeKeyboard, 900);
    }

    private void loadConnectionConfig() {
        SharedPreferences prefs = getSharedPreferences(PREFS_NAME, MODE_PRIVATE);
        baseUrl = prefs.getString(PREF_BASE_URL, DEFAULT_BASE_URL);
        mouseHost = prefs.getString(PREF_MOUSE_HOST, DEFAULT_MOUSE_HOST);
        accessKey = prefs.getString(PREF_KEY, DEFAULT_KEY);
    }

    private void saveConnectionConfig(String newBaseUrl, String newMouseHost, String newKey) {
        if (newBaseUrl == null || newBaseUrl.isEmpty() || newMouseHost == null || newMouseHost.isEmpty()
                || newKey == null || newKey.isEmpty()) {
            return;
        }
        boolean changed = !newBaseUrl.equals(baseUrl) || !newMouseHost.equals(mouseHost) || !newKey.equals(accessKey);
        baseUrl = newBaseUrl;
        mouseHost = newMouseHost;
        accessKey = newKey;
        getSharedPreferences(PREFS_NAME, MODE_PRIVATE)
                .edit()
                .putString(PREF_BASE_URL, baseUrl)
                .putString(PREF_MOUSE_HOST, mouseHost)
                .putString(PREF_KEY, accessKey)
                .apply();
        if (changed) {
            synchronized (mouseLock) {
                mouseAddress = null;
            }
            runOnUiThread(() -> {
                setDot(computerDot, true);
                showFlash("已自动更新电脑连接");
                fetchSnapshot(false);
            });
        }
    }

    private void discoverDesktopService() {
        discoveryNetwork.execute(() -> {
            byte[] request = DISCOVERY_MESSAGE.getBytes(StandardCharsets.UTF_8);
            for (int attempt = 0; attempt < 3 && running; attempt++) {
                try (DatagramSocket socket = new DatagramSocket()) {
                    socket.setBroadcast(true);
                    socket.setSoTimeout(900);
                    DatagramPacket packet = new DatagramPacket(
                            request,
                            request.length,
                            InetAddress.getByName("255.255.255.255"),
                            MOUSE_PORT
                    );
                    socket.send(packet);
                    byte[] buffer = new byte[2048];
                    DatagramPacket response = new DatagramPacket(buffer, buffer.length);
                    socket.receive(response);
                    String body = new String(response.getData(), 0, response.getLength(), StandardCharsets.UTF_8);
                    JSONObject json = new JSONObject(body);
                    if (!json.optBoolean("ok", false) || !"phone_input_sync".equals(json.optString("name", ""))) {
                        continue;
                    }
                    String host = json.optString("host", response.getAddress().getHostAddress());
                    int port = json.optInt("port", MOUSE_PORT);
                    String discoveredBaseUrl = json.optString("base_url", "http://" + host + ":" + port);
                    String key = json.optString("key", "");
                    saveConnectionConfig(discoveredBaseUrl, host, key);
                    return;
                } catch (SocketTimeoutException ignored) {
                } catch (Exception ignored) {
                    return;
                }
            }
        });
    }

    private void startVoiceInput() {
        runOnUiThread(() -> {
            if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
                requestPermissions(new String[]{Manifest.permission.RECORD_AUDIO}, REQUEST_RECORD_AUDIO);
                return;
            }
            launchVoiceRecognizer();
        });
    }

    private void launchVoiceRecognizer() {
        try {
            input.requestFocus();
            Intent intent = new Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH);
            intent.putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM);
            intent.putExtra(RecognizerIntent.EXTRA_LANGUAGE, Locale.getDefault());
            intent.putExtra(RecognizerIntent.EXTRA_PROMPT, "开始说话");
            startActivityForResult(intent, REQUEST_VOICE_INPUT);
        } catch (Exception exc) {
            showFlash("手机没有可用的语音识别");
            wakeKeyboard();
        }
    }

    private void insertVoiceText(String text) {
        if (text == null || text.trim().isEmpty()) {
            wakeKeyboard();
            return;
        }
        String value = text.trim();
        int start = Math.max(0, input.getSelectionStart());
        int end = Math.max(0, input.getSelectionEnd());
        int insertStart = Math.min(start, end);
        int insertEnd = Math.max(start, end);
        Editable editable = input.getText();
        editable.replace(insertStart, insertEnd, value);
        input.setSelection(insertStart + value.length());
        wakeKeyboard();
    }

    private void fetchSnapshot() {
        fetchSnapshot(false);
    }

    private void fetchSnapshot(boolean force) {
        long now = System.currentTimeMillis();
        if (!force && now - lastSnapshotRequestMs < 1200) {
            return;
        }
        if (!force && now - lastLocalEditMs < LOCAL_EDIT_PROTECT_MS) {
            return;
        }
        lastSnapshotRequestMs = now;
        final String baseText = previous;
        snapshotNetwork.execute(() -> {
            HttpURLConnection connection = null;
            try {
                URL url = new URL(baseUrl + "/snapshot?key=" + accessKey);
                connection = (HttpURLConnection) url.openConnection();
                connection.setRequestMethod("GET");
                connection.setConnectTimeout(1200);
                connection.setReadTimeout(2000);
                if (connection.getResponseCode() != 200) {
                    runOnUiThread(() -> {
                        setDot(computerDot, false);
                        setDot(inputDot, false);
                        setDot(syncDot, false);
                        showFlash("请确认电脑服务已启动");
                    });
                    return;
                }
                runOnUiThread(() -> setDot(computerDot, true));
                StringBuilder body = new StringBuilder();
                try (BufferedReader reader = new BufferedReader(
                        new InputStreamReader(connection.getInputStream(), StandardCharsets.UTF_8)
                )) {
                    String line;
                    while ((line = reader.readLine()) != null) {
                        body.append(line);
                    }
                }
                JSONObject json = new JSONObject(body.toString());
                if (!json.optBoolean("ok", false)) {
                    runOnUiThread(() -> {
                        setInputDotWaiting();
                        setDot(syncDot, false);
                        showFlash("已连接电脑，请先点电脑输入框");
                    });
                    return;
                }
                String text = json.optString("text", "");
                runOnUiThread(() -> {
                    long applyNow = System.currentTimeMillis();
                    String localText = input.getText().toString();
                    if (text.isEmpty() && !localText.isEmpty()) {
                        setDot(inputDot, true);
                        setDot(syncDot, true);
                        return;
                    }
                    if ((force || applyNow - lastLocalEditMs >= LOCAL_EDIT_PROTECT_MS)
                            && input.getText().toString().equals(baseText)) {
                        applySnapshotText(text);
                        setDot(inputDot, true);
                        setDot(syncDot, true);
                        showFlash("已连接电脑，已读取电脑输入框");
                    }
                });
            } catch (Exception ignored) {
                runOnUiThread(() -> {
                    setDot(computerDot, false);
                    setDot(inputDot, false);
                    setDot(syncDot, false);
                    showFlash("请确认电脑服务已启动");
                });
            } finally {
                if (connection != null) {
                    connection.disconnect();
                }
            }
        });
    }

    private void openPhotoPicker() {
        Intent intent = new Intent(Intent.ACTION_OPEN_DOCUMENT);
        intent.addCategory(Intent.CATEGORY_OPENABLE);
        intent.setType("image/*");
        startActivityForResult(intent, REQUEST_PICK_IMAGE);
    }

    private void handleIncomingImage(Intent intent) {
        if (intent == null || !Intent.ACTION_SEND.equals(intent.getAction())) {
            return;
        }
        Uri imageUri = intent.getParcelableExtra(Intent.EXTRA_STREAM);
        if (imageUri != null) {
            uploadImage(imageUri);
        }
    }

    private String getDisplayName(Uri uri) {
        String name = null;
        try (Cursor cursor = getContentResolver().query(uri, null, null, null, null)) {
            if (cursor != null && cursor.moveToFirst()) {
                int index = cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME);
                if (index >= 0) {
                    name = cursor.getString(index);
                }
            }
        } catch (Exception ignored) {
        }
        if (name == null || name.trim().isEmpty()) {
            name = "phone_image.jpg";
        }
        return name;
    }

    private void uploadImage(Uri uri) {
        network.execute(() -> {
            HttpURLConnection connection = null;
            try (InputStream in = getContentResolver().openInputStream(uri)) {
                if (in == null) {
                    return;
                }
                ByteArrayOutputStream imageBytes = new ByteArrayOutputStream();
                byte[] buffer = new byte[64 * 1024];
                int read;
                while ((read = in.read(buffer)) != -1) {
                    imageBytes.write(buffer, 0, read);
                    if (imageBytes.size() > MAX_IMAGE_BYTES) {
                        return;
                    }
                }
                byte[] body = imageBytes.toByteArray();
                String filename = URLEncoder.encode(getDisplayName(uri), "UTF-8");
                URL url = new URL(baseUrl + "/upload?key=" + accessKey + "&filename=" + filename);
                connection = (HttpURLConnection) url.openConnection();
                connection.setRequestMethod("POST");
                connection.setConnectTimeout(2500);
                connection.setReadTimeout(20000);
                connection.setDoOutput(true);
                connection.setFixedLengthStreamingMode(body.length);
                String contentType = getContentResolver().getType(uri);
                connection.setRequestProperty("Content-Type", contentType != null ? contentType : "image/jpeg");

                try (OutputStream out = connection.getOutputStream()) {
                    out.write(body);
                }
                connection.getResponseCode();
            } catch (Exception ignored) {
            } finally {
                if (connection != null) {
                    connection.disconnect();
                }
                runOnUiThread(this::wakeKeyboard);
            }
        });
    }

    private SyncOp diff(String oldText, String newText) {
        int prefix = 0;
        int oldLen = oldText.length();
        int newLen = newText.length();
        while (prefix < oldLen && prefix < newLen && oldText.charAt(prefix) == newText.charAt(prefix)) {
            prefix++;
        }
        int suffix = 0;
        while (
                suffix < oldLen - prefix
                        && suffix < newLen - prefix
                        && oldText.charAt(oldLen - 1 - suffix) == newText.charAt(newLen - 1 - suffix)
        ) {
            suffix++;
        }
        int deleteCount = oldLen - prefix - suffix;
        String insertText = newText.substring(prefix, newLen - suffix);
        return new SyncOp(deleteCount, insertText, suffix);
    }

    private void postSync(int deleteCount, String insertText, int suffixCount, boolean enter, String fullText) {
        int revision = syncRevision.incrementAndGet();
        network.execute(() -> {
            if (!enter && revision != syncRevision.get()) {
                return;
            }
            HttpURLConnection connection = null;
            try {
                URL url = new URL(baseUrl + "/sync?key=" + accessKey);
                connection = (HttpURLConnection) url.openConnection();
                connection.setRequestMethod("POST");
                connection.setConnectTimeout(1800);
                connection.setReadTimeout(1800);
                connection.setDoOutput(true);
                connection.setRequestProperty("Content-Type", "application/json; charset=utf-8");

                JSONObject json = new JSONObject();
                json.put("delete", deleteCount);
                json.put("insert", insertText);
                json.put("suffix", suffixCount);
                json.put("enter", enter);
                json.put("text", fullText);
                byte[] body = json.toString().getBytes(StandardCharsets.UTF_8);
                connection.setFixedLengthStreamingMode(body.length);

                try (OutputStream out = connection.getOutputStream()) {
                    out.write(body);
                }
                connection.getResponseCode();
            } catch (Exception ignored) {
            } finally {
                if (connection != null) {
                    connection.disconnect();
                }
            }
        });
    }

    private void postMouse(float dx, float dy, float wheelX, float wheelY, String action) {
        if (action == null || action.isEmpty()) {
            synchronized (mouseLock) {
                pendingMouseDx += dx;
                pendingMouseDy += dy;
                pendingWheelX += wheelX;
                pendingWheelY += wheelY;
            }
            if (mouseFlushScheduled.compareAndSet(false, true)) {
                input.post(this::flushMouseMove);
            }
            return;
        }
        postMouseRequest(dx, dy, wheelX, wheelY, action);
    }

    private void flushMouseMove() {
        final float dx;
        final float dy;
        final float wheelX;
        final float wheelY;
        synchronized (mouseLock) {
            dx = pendingMouseDx;
            dy = pendingMouseDy;
            wheelX = pendingWheelX;
            wheelY = pendingWheelY;
            pendingMouseDx = 0f;
            pendingMouseDy = 0f;
            pendingWheelX = 0f;
            pendingWheelY = 0f;
        }
        mouseFlushScheduled.set(false);
        postMouseDatagram(dx, dy, wheelX, wheelY);
    }

    private void postMouseDatagram(float dx, float dy, float wheelX, float wheelY) {
        mouseNetwork.execute(() -> {
            try {
                if (mouseAddress == null) {
                    mouseAddress = InetAddress.getByName(mouseHost);
                }
                if (mouseSocket == null || mouseSocket.isClosed()) {
                    mouseSocket = new DatagramSocket();
                }
                float exactDx;
                float exactDy;
                float exactWheelX;
                float exactWheelY;
                synchronized (mouseLock) {
                    exactDx = dx + mouseRemainderDx;
                    exactDy = dy + mouseRemainderDy;
                    exactWheelX = wheelX + wheelRemainderX;
                    exactWheelY = wheelY + wheelRemainderY;
                }
                int outDx = Math.round(exactDx);
                int outDy = Math.round(exactDy);
                int outWheelX = Math.round(exactWheelX);
                int outWheelY = Math.round(exactWheelY);
                synchronized (mouseLock) {
                    mouseRemainderDx = exactDx - outDx;
                    mouseRemainderDy = exactDy - outDy;
                    wheelRemainderX = exactWheelX - outWheelX;
                    wheelRemainderY = exactWheelY - outWheelY;
                }
                if (outDx == 0 && outDy == 0 && outWheelX == 0 && outWheelY == 0) {
                    return;
                }
                JSONObject json = new JSONObject();
                json.put("key", accessKey);
                json.put("dx", outDx);
                json.put("dy", outDy);
                json.put("wheelX", outWheelX);
                json.put("wheelY", outWheelY);
                json.put("action", "");
                byte[] body = json.toString().getBytes(StandardCharsets.UTF_8);
                mouseSocket.send(new DatagramPacket(body, body.length, mouseAddress, MOUSE_PORT));
            } catch (Exception ignored) {
            }
        });
    }

    private void postMouseRequest(float dx, float dy, float wheelX, float wheelY, String action) {
        mouseNetwork.execute(() -> {
            HttpURLConnection connection = null;
            try {
                URL url = new URL(baseUrl + "/mouse?key=" + accessKey);
                connection = (HttpURLConnection) url.openConnection();
                connection.setRequestMethod("POST");
                connection.setConnectTimeout(450);
                connection.setReadTimeout(450);
                connection.setDoOutput(true);
                connection.setRequestProperty("Content-Type", "application/json; charset=utf-8");

                JSONObject json = new JSONObject();
                json.put("dx", Math.round(dx));
                json.put("dy", Math.round(dy));
                json.put("wheelX", Math.round(wheelX));
                json.put("wheelY", Math.round(wheelY));
                json.put("action", action);
                byte[] body = json.toString().getBytes(StandardCharsets.UTF_8);
                connection.setFixedLengthStreamingMode(body.length);

                try (OutputStream out = connection.getOutputStream()) {
                    out.write(body);
                }
                connection.getResponseCode();
            } catch (Exception ignored) {
            } finally {
                if (connection != null) {
                    connection.disconnect();
                }
                if (action == null || action.isEmpty()) {
                    mouseRequestInFlight.set(false);
                    boolean hasPending;
                    synchronized (mouseLock) {
                        hasPending = Math.abs(pendingMouseDx) >= 1f
                                || Math.abs(pendingMouseDy) >= 1f
                                || Math.abs(pendingWheelX) >= 1f
                                || Math.abs(pendingWheelY) >= 1f;
                    }
                    if (hasPending && mouseFlushScheduled.compareAndSet(false, true)) {
                        input.post(this::flushMouseMove);
                    }
                }
            }
        });
    }

    private void startFocusEvents() {
        Thread thread = new Thread(() -> {
            while (running) {
                HttpURLConnection connection = null;
                try {
                    URL url = new URL(baseUrl + "/events?key=" + accessKey);
                    connection = (HttpURLConnection) url.openConnection();
                    connection.setConnectTimeout(2500);
                    connection.setReadTimeout(0);
                    connection.setRequestProperty("Accept", "text/event-stream");

                    try (BufferedReader reader = new BufferedReader(
                            new InputStreamReader(connection.getInputStream(), StandardCharsets.UTF_8)
                    )) {
                        String line;
                        while (running && (line = reader.readLine()) != null) {
                            if (line.startsWith("event: focus")) {
                                runOnUiThread(this::wakeKeyboard);
                            } else if (line.startsWith("event: voice")) {
                                startVoiceInput();
                            } else if (line.startsWith("event: clear")) {
                                runOnUiThread(() -> {
                                    clearLocalText();
                                    wakeKeyboard();
                                });
                            }
                        }
                    }
                } catch (Exception ignored) {
                    try {
                        Thread.sleep(1000);
                    } catch (InterruptedException e) {
                        return;
                    }
                } finally {
                    if (connection != null) {
                        connection.disconnect();
                    }
                }
            }
        }, "focus-events");
        thread.setDaemon(true);
        thread.start();
    }

    private static class SyncOp {
        final int deleteCount;
        final String insertText;
        final int suffixCount;

        SyncOp(int deleteCount, String insertText, int suffixCount) {
            this.deleteCount = deleteCount;
            this.insertText = insertText;
            this.suffixCount = suffixCount;
        }
    }

    public static class SyncEditText extends EditText {
        private static final float MOUSE_SCALE = 0.95f;
        private static final float WHEEL_SCALE = 2.6f;
        private static final float TOUCHPAD_PADDING_PX = 72f;
        private static final float TAP_SLOP_PX = 24f;
        private static final long TAP_TIMEOUT_MS = 240;
        private static final long DOUBLE_TAP_TIMEOUT_MS = 320;
        private static final long DRAG_START_MS = 360;
        private static final long PHOTO_TAP_WINDOW_MS = 1200;
        private static final int PHOTO_TAP_COUNT = 5;

        private Runnable sendListener;
        private Runnable remoteDeleteListener;
        private Runnable photoPickerListener;
        private TouchpadListener touchpadListener;
        private boolean touchpadActive = false;
        private float downX;
        private float downY;
        private float lastX;
        private float lastY;
        private float lastTwoFingerX;
        private float lastTwoFingerY;
        private float twoFingerDownX;
        private float twoFingerDownY;
        private long downTimeMs;
        private long twoFingerDownTimeMs;
        private boolean twoFingerMoved = false;
        private boolean dragActive = false;
        private long firstPhotoTapMs = 0L;
        private int photoTapCount = 0;
        private Runnable pendingClickRunnable;
        private Runnable pendingDragRunnable;

        public SyncEditText(Context context) {
            super(context);
        }

        public SyncEditText(Context context, AttributeSet attrs) {
            super(context, attrs);
        }

        public void setSendListener(Runnable sendListener) {
            this.sendListener = sendListener;
        }

        public void setRemoteDeleteListener(Runnable remoteDeleteListener) {
            this.remoteDeleteListener = remoteDeleteListener;
        }

        public void setPhotoPickerListener(Runnable photoPickerListener) {
            this.photoPickerListener = photoPickerListener;
        }

        public void setTouchpadListener(TouchpadListener touchpadListener) {
            this.touchpadListener = touchpadListener;
        }

        @Override
        public boolean onTouchEvent(MotionEvent event) {
            int action = event.getActionMasked();
            if (event.getPointerCount() >= 2) {
                float centerX = (event.getX(0) + event.getX(1)) / 2f;
                float centerY = (event.getY(0) + event.getY(1)) / 2f;
                if ((action == MotionEvent.ACTION_POINTER_DOWN || action == MotionEvent.ACTION_DOWN)
                        && (isTouchpadZone(event.getY(0)) || isTouchpadZone(event.getY(1)))) {
                    touchpadActive = true;
                    lastTwoFingerX = twoFingerDownX = centerX;
                    lastTwoFingerY = twoFingerDownY = centerY;
                    twoFingerDownTimeMs = System.currentTimeMillis();
                    twoFingerMoved = false;
                    cancelDragStart();
                    return true;
                }
                if (touchpadActive && action == MotionEvent.ACTION_MOVE) {
                    float dx = (centerX - lastTwoFingerX) * WHEEL_SCALE;
                    float dy = (centerY - lastTwoFingerY) * WHEEL_SCALE;
                    lastTwoFingerX = centerX;
                    lastTwoFingerY = centerY;
                    twoFingerMoved = twoFingerMoved
                            || Math.hypot(centerX - twoFingerDownX, centerY - twoFingerDownY) > TAP_SLOP_PX;
                    if ((Math.abs(dx) >= 1f || Math.abs(dy) >= 1f) && touchpadListener != null) {
                        touchpadListener.onTouchpad(0, 0, dx, dy, "");
                    }
                    return true;
                }
                if (touchpadActive && (action == MotionEvent.ACTION_UP || action == MotionEvent.ACTION_CANCEL || action == MotionEvent.ACTION_POINTER_UP)) {
                    long duration = System.currentTimeMillis() - twoFingerDownTimeMs;
                    if (action != MotionEvent.ACTION_CANCEL
                            && duration <= TAP_TIMEOUT_MS
                            && !twoFingerMoved
                            && touchpadListener != null) {
                        touchpadListener.onTouchpad(0, 0, 0, 0, "rightClick");
                    }
                    touchpadActive = false;
                    return true;
                }
            } else if (event.getPointerCount() == 1) {
                if (action == MotionEvent.ACTION_DOWN && isTouchpadZone(event.getY())) {
                    touchpadActive = true;
                    downX = lastX = event.getX();
                    downY = lastY = event.getY();
                    downTimeMs = System.currentTimeMillis();
                    dragActive = false;
                    scheduleDragStart();
                    requestFocus();
                    setSelection(getText().length());
                    return true;
                }
                if (touchpadActive) {
                    if (action == MotionEvent.ACTION_MOVE) {
                        float totalDx = event.getX() - downX;
                        float totalDy = event.getY() - downY;
                        if (!dragActive && Math.hypot(totalDx, totalDy) > TAP_SLOP_PX) {
                            cancelDragStart();
                        }
                        float dx = (event.getX() - lastX) * MOUSE_SCALE;
                        float dy = (event.getY() - lastY) * MOUSE_SCALE;
                        lastX = event.getX();
                        lastY = event.getY();
                        if ((Math.abs(dx) >= 1f || Math.abs(dy) >= 1f) && touchpadListener != null) {
                            touchpadListener.onTouchpad(dx, dy, 0, 0, "");
                        }
                        return true;
                    }
                    if (action == MotionEvent.ACTION_UP || action == MotionEvent.ACTION_CANCEL) {
                        cancelDragStart();
                        float totalDx = event.getX() - downX;
                        float totalDy = event.getY() - downY;
                        long duration = System.currentTimeMillis() - downTimeMs;
                        boolean click = action == MotionEvent.ACTION_UP
                                && duration <= TAP_TIMEOUT_MS
                                && Math.hypot(totalDx, totalDy) <= TAP_SLOP_PX;
                        touchpadActive = false;
                        if (dragActive) {
                            dragActive = false;
                            if (touchpadListener != null) {
                                touchpadListener.onTouchpad(0, 0, 0, 0, "dragEnd");
                            }
                            return true;
                        }
                        if (click) {
                            performClick();
                            if (recordPhotoTap() && photoPickerListener != null) {
                                if (pendingClickRunnable != null) {
                                    removeCallbacks(pendingClickRunnable);
                                    pendingClickRunnable = null;
                                }
                                photoTapCount = 0;
                                firstPhotoTapMs = 0L;
                                photoPickerListener.run();
                                return true;
                            }
                            scheduleMouseClick();
                        }
                        return true;
                    }
                }
            }
            touchpadActive = false;
            return super.onTouchEvent(event);
        }

        @Override
        public boolean performClick() {
            super.performClick();
            return true;
        }

        private boolean isTouchpadZone(float y) {
            if (getLayout() == null) {
                return false;
            }
            int lineCount = Math.max(1, getLineCount());
            int lastLineBottom = getLayout().getLineBottom(lineCount - 1) + getCompoundPaddingTop();
            return y > lastLineBottom + TOUCHPAD_PADDING_PX;
        }

        private boolean recordPhotoTap() {
            long now = System.currentTimeMillis();
            if (firstPhotoTapMs == 0L || now - firstPhotoTapMs > PHOTO_TAP_WINDOW_MS) {
                firstPhotoTapMs = now;
                photoTapCount = 1;
            } else {
                photoTapCount++;
            }
            return photoTapCount >= PHOTO_TAP_COUNT;
        }

        private void scheduleDragStart() {
            cancelDragStart();
            pendingDragRunnable = () -> {
                pendingDragRunnable = null;
                if (touchpadActive && !dragActive && touchpadListener != null) {
                    dragActive = true;
                    touchpadListener.onTouchpad(0, 0, 0, 0, "dragStart");
                }
            };
            postDelayed(pendingDragRunnable, DRAG_START_MS);
        }

        private void cancelDragStart() {
            if (pendingDragRunnable != null) {
                removeCallbacks(pendingDragRunnable);
                pendingDragRunnable = null;
            }
        }

        private void scheduleMouseClick() {
            if (pendingClickRunnable != null) {
                removeCallbacks(pendingClickRunnable);
                pendingClickRunnable = null;
                if (touchpadListener != null) {
                    touchpadListener.onTouchpad(0, 0, 0, 0, "doubleClick");
                }
                return;
            }
            pendingClickRunnable = () -> {
                pendingClickRunnable = null;
                if (touchpadListener != null) {
                    touchpadListener.onTouchpad(0, 0, 0, 0, "click");
                }
            };
            postDelayed(pendingClickRunnable, DOUBLE_TAP_TIMEOUT_MS);
        }

        @Override
        public InputConnection onCreateInputConnection(EditorInfo outAttrs) {
            InputConnection base = super.onCreateInputConnection(outAttrs);
            outAttrs.imeOptions &= ~EditorInfo.IME_FLAG_NO_ENTER_ACTION;
            outAttrs.imeOptions |= EditorInfo.IME_ACTION_SEND | EditorInfo.IME_FLAG_NO_EXTRACT_UI;
            outAttrs.inputType = InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_FLAG_CAP_SENTENCES;
            return new InputConnectionWrapper(base, true) {
                @Override
                public boolean performEditorAction(int editorAction) {
                    if (editorAction == EditorInfo.IME_ACTION_SEND
                            || editorAction == EditorInfo.IME_ACTION_DONE
                            || editorAction == EditorInfo.IME_ACTION_GO) {
                        triggerSend();
                        return true;
                    }
                    return super.performEditorAction(editorAction);
                }

                @Override
                public boolean sendKeyEvent(KeyEvent event) {
                    if (event.getKeyCode() == KeyEvent.KEYCODE_ENTER && event.getAction() == KeyEvent.ACTION_UP) {
                        triggerSend();
                        return true;
                    }
                    if (event.getKeyCode() == KeyEvent.KEYCODE_DEL
                            && event.getAction() == KeyEvent.ACTION_UP
                            && getText().length() == 0) {
                        triggerRemoteDelete();
                        return true;
                    }
                    return super.sendKeyEvent(event);
                }

                @Override
                public boolean deleteSurroundingText(int beforeLength, int afterLength) {
                    if (beforeLength > 0 && getText().length() == 0) {
                        triggerRemoteDelete();
                        return true;
                    }
                    return super.deleteSurroundingText(beforeLength, afterLength);
                }

                @Override
                public boolean deleteSurroundingTextInCodePoints(int beforeLength, int afterLength) {
                    if (beforeLength > 0 && getText().length() == 0) {
                        triggerRemoteDelete();
                        return true;
                    }
                    return super.deleteSurroundingTextInCodePoints(beforeLength, afterLength);
                }

                @Override
                public boolean commitText(CharSequence text, int newCursorPosition) {
                    if (text != null && text.toString().contains("\n")) {
                        String cleaned = text.toString().replace("\r", "").replace("\n", "");
                        if (!cleaned.isEmpty()) {
                            super.commitText(cleaned, newCursorPosition);
                        }
                        triggerSend();
                        return true;
                    }
                    return super.commitText(text, newCursorPosition);
                }
            };
        }

        private void triggerSend() {
            if (sendListener != null) {
                post(sendListener);
            }
        }

        private void triggerRemoteDelete() {
            if (remoteDeleteListener != null) {
                post(remoteDeleteListener);
            }
        }

        public interface TouchpadListener {
            void onTouchpad(float dx, float dy, float wheelX, float wheelY, String action);
        }
    }
}
