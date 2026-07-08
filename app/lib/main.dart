// Spidey on every screen. Dark Spidey theme, chat with the agent, tap-to-talk
// voice in, spoken replies out — all against a Spidey server you point it at
// (usually `spidey serve` on the same machine or your LAN).

import 'package:flutter/material.dart';
import 'package:flutter_tts/flutter_tts.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:speech_to_text/speech_to_text.dart';

import 'spidey_client.dart';

const spideyRed = Color(0xFFC81E24);
const spideyRedBright = Color(0xFFEF3A40);
const spideyBlue = Color(0xFF2545A8);
const spideyBlueDeep = Color(0xFF16204D);

void main() => runApp(const SpideyApp());

class SpideyApp extends StatelessWidget {
  const SpideyApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Spidey',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        brightness: Brightness.dark,
        colorScheme: ColorScheme.fromSeed(
          seedColor: spideyRed,
          brightness: Brightness.dark,
          primary: spideyRedBright,
          secondary: spideyBlue,
          surface: const Color(0xFF0B0B10),
        ),
        scaffoldBackgroundColor: const Color(0xFF0B0B10),
        fontFamily: 'Roboto',
      ),
      home: const ChatScreen(),
    );
  }
}

class ChatScreen extends StatefulWidget {
  const ChatScreen({super.key});

  @override
  State<ChatScreen> createState() => _ChatScreenState();
}

class _ChatScreenState extends State<ChatScreen> {
  final client = SpideyClient();
  final config = SpideyConfig();
  final input = TextEditingController();
  final scroll = ScrollController();
  final stt = SpeechToText();
  final tts = FlutterTts();
  bool speechReady = false;
  bool listening = false;
  bool speakReplies = true;
  String? _spokenLast;

  @override
  void initState() {
    super.initState();
    client.addListener(_onClient);
    _load();
  }

  Future<void> _load() async {
    final prefs = await SharedPreferences.getInstance();
    config
      ..serverUrl = prefs.getString('serverUrl') ?? config.serverUrl
      ..provider = prefs.getString('provider') ?? config.provider
      ..model = prefs.getString('model') ?? ''
      ..apiKey = prefs.getString('apiKey') ?? ''
      ..safety = prefs.getString('safety') ?? 'ask';
    speakReplies = prefs.getBool('speakReplies') ?? true;
    client.connect(config.serverUrl);
    speechReady = await stt.initialize();
    if (mounted) setState(() {});
  }

  void _onClient() {
    setState(() {});
    final say = client.lastSpoken;
    if (speakReplies && say != null && say != _spokenLast) {
      _spokenLast = say;
      tts.speak(say);
    }
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (scroll.hasClients) scroll.jumpTo(scroll.position.maxScrollExtent);
    });
  }

  void _send([String? text]) {
    final task = (text ?? input.text).trim();
    if (task.isEmpty || client.running || !client.connected) return;
    input.clear();
    client.start(task, config);
  }

  Future<void> _mic() async {
    if (!speechReady) return;
    if (listening) {
      await stt.stop();
      setState(() => listening = false);
      return;
    }
    setState(() => listening = true);
    await stt.listen(
      listenOptions: SpeechListenOptions(partialResults: true, onDevice: true),
      onResult: (r) {
        setState(() => input.text = r.recognizedWords);
        if (r.finalResult) {
          setState(() => listening = false);
          _send(r.recognizedWords);
        }
      },
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        backgroundColor: const Color(0xFF0B0B10),
        title: Row(children: [
          const Text('🕷️ '),
          const Text('Spidey', style: TextStyle(fontWeight: FontWeight.bold)),
          const SizedBox(width: 8),
          Text(
            client.connected ? '● connected' : '○ offline',
            style: TextStyle(
              fontSize: 12,
              color: client.connected ? Colors.greenAccent : spideyRedBright,
            ),
          ),
        ]),
        actions: [
          IconButton(
            icon: Icon(speakReplies ? Icons.volume_up : Icons.volume_off),
            color: speakReplies ? spideyBlue : Colors.grey,
            onPressed: () async {
              setState(() => speakReplies = !speakReplies);
              (await SharedPreferences.getInstance())
                  .setBool('speakReplies', speakReplies);
            },
          ),
          IconButton(
            icon: const Icon(Icons.settings),
            onPressed: () => _openSettings(context),
          ),
        ],
      ),
      body: Column(children: [
        Expanded(
          child: client.messages.isEmpty
              ? const Center(
                  child: Text(
                    '🕷️\nYour friendly neighborhood AI.\nType a task, or tap the mic.',
                    textAlign: TextAlign.center,
                    style: TextStyle(color: Colors.grey, height: 1.6),
                  ),
                )
              : ListView.builder(
                  controller: scroll,
                  padding: const EdgeInsets.all(12),
                  itemCount: client.messages.length,
                  itemBuilder: (_, i) => _bubble(client.messages[i]),
                ),
        ),
        SafeArea(
          child: Padding(
            padding: const EdgeInsets.fromLTRB(12, 4, 12, 12),
            child: Row(children: [
              Expanded(
                child: TextField(
                  controller: input,
                  onSubmitted: (_) => _send(),
                  decoration: InputDecoration(
                    hintText: listening
                        ? 'Listening…'
                        : client.connected
                            ? 'Describe a task…'
                            : 'Connecting…',
                    filled: true,
                    fillColor: const Color(0xFF17171E),
                    border: OutlineInputBorder(
                      borderRadius: BorderRadius.circular(12),
                      borderSide: BorderSide.none,
                    ),
                  ),
                ),
              ),
              const SizedBox(width: 8),
              IconButton.filled(
                onPressed: speechReady ? _mic : null,
                style: IconButton.styleFrom(
                  backgroundColor: listening ? spideyRedBright : const Color(0xFF27272E),
                ),
                icon: Icon(listening ? Icons.mic : Icons.mic_none),
              ),
              const SizedBox(width: 8),
              client.running
                  ? IconButton.filled(
                      onPressed: client.stop,
                      style: IconButton.styleFrom(backgroundColor: spideyRed),
                      icon: const Icon(Icons.stop),
                    )
                  : IconButton.filled(
                      onPressed: _send,
                      style: IconButton.styleFrom(backgroundColor: spideyRed),
                      icon: const Icon(Icons.send),
                    ),
            ]),
          ),
        ),
      ]),
    );
  }

  Widget _bubble(ChatMsg m) {
    switch (m.kind) {
      case MsgKind.user:
        return _card(m.text, bg: spideyRed, align: Alignment.centerRight);
      case MsgKind.agent:
        return _card(m.text, bg: spideyBlueDeep, align: Alignment.centerLeft);
      case MsgKind.think:
        return _card('🧠 ${m.text}',
            fg: Colors.grey, align: Alignment.centerLeft, flat: true);
      case MsgKind.tool:
        final icon = m.status == 'ok' ? '✓' : m.status == 'err' ? '✗' : '⏳';
        return _card('$icon ${m.tool} ${m.args ?? ''}',
            fg: Colors.blueGrey.shade200, align: Alignment.centerLeft, flat: true);
      case MsgKind.finish:
        return _card('🏁 ${m.text}',
            bg: const Color(0xFF10321F), align: Alignment.centerLeft);
      case MsgKind.error:
        return _card(m.text, bg: const Color(0xFF3A1114), align: Alignment.centerLeft);
      case MsgKind.approval:
        return Card(
          color: const Color(0xFF33270D),
          margin: const EdgeInsets.symmetric(vertical: 4),
          child: Padding(
            padding: const EdgeInsets.all(12),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text('⚠ Spidey-sense — approval needed',
                    style: TextStyle(color: Colors.amber, fontWeight: FontWeight.bold)),
                const SizedBox(height: 6),
                Text(m.text, style: const TextStyle(fontFamily: 'monospace', fontSize: 12)),
                const SizedBox(height: 8),
                if (m.resolved == null && m.id != null)
                  Row(children: [
                    FilledButton(
                      style: FilledButton.styleFrom(backgroundColor: Colors.green.shade700),
                      onPressed: () => client.answerApproval(m.id!, true),
                      child: const Text('Approve'),
                    ),
                    const SizedBox(width: 8),
                    FilledButton(
                      style: FilledButton.styleFrom(backgroundColor: spideyRed),
                      onPressed: () => client.answerApproval(m.id!, false),
                      child: const Text('Deny'),
                    ),
                  ])
                else if (m.resolved != null)
                  Text(m.resolved! ? '✓ approved' : '✗ denied',
                      style: TextStyle(
                          color: m.resolved! ? Colors.greenAccent : spideyRedBright)),
              ],
            ),
          ),
        );
    }
  }

  Widget _card(String text,
      {Color? bg, Color? fg, required Alignment align, bool flat = false}) {
    return Align(
      alignment: align,
      child: Container(
        margin: const EdgeInsets.symmetric(vertical: 3),
        padding: flat
            ? const EdgeInsets.symmetric(horizontal: 4, vertical: 2)
            : const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
        constraints: const BoxConstraints(maxWidth: 560),
        decoration: flat
            ? null
            : BoxDecoration(color: bg, borderRadius: BorderRadius.circular(14)),
        child: Text(text, style: TextStyle(color: fg, fontSize: 14, height: 1.35)),
      ),
    );
  }

  Future<void> _openSettings(BuildContext context) async {
    await showDialog(
      context: context,
      builder: (_) => SettingsDialog(config: config),
    );
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString('serverUrl', config.serverUrl);
    await prefs.setString('provider', config.provider);
    await prefs.setString('model', config.model);
    await prefs.setString('apiKey', config.apiKey);
    await prefs.setString('safety', config.safety);
    client.connect(config.serverUrl);
  }

  @override
  void dispose() {
    client.dispose();
    input.dispose();
    scroll.dispose();
    super.dispose();
  }
}

class SettingsDialog extends StatefulWidget {
  const SettingsDialog({super.key, required this.config});
  final SpideyConfig config;

  @override
  State<SettingsDialog> createState() => _SettingsDialogState();
}

class _SettingsDialogState extends State<SettingsDialog> {
  static const providers = {
    'ollama': 'Ollama — local, private, offline',
    'anthropic': 'Claude (Anthropic)',
    'gemini': 'Gemini (Google)',
    'openai': 'OpenAI',
  };

  @override
  Widget build(BuildContext context) {
    final c = widget.config;
    return AlertDialog(
      title: const Text('Settings'),
      content: SingleChildScrollView(
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          TextFormField(
            initialValue: c.serverUrl,
            decoration: const InputDecoration(
                labelText: 'Spidey server URL',
                helperText: 'Where `spidey serve` runs — this device or your LAN'),
            onChanged: (v) => c.serverUrl = v.trim(),
          ),
          DropdownButtonFormField<String>(
            initialValue: c.provider,
            decoration: const InputDecoration(labelText: 'Provider'),
            items: [
              for (final e in providers.entries)
                DropdownMenuItem(value: e.key, child: Text(e.value)),
            ],
            onChanged: (v) => setState(() => c.provider = v ?? 'ollama'),
          ),
          TextFormField(
            initialValue: c.model,
            decoration: const InputDecoration(
                labelText: 'Model', hintText: 'e.g. gemma4:12b · qwen2.5-coder:7b'),
            onChanged: (v) => c.model = v.trim(),
          ),
          if (c.provider == 'anthropic' || c.provider == 'gemini' || c.provider == 'openai')
            TextFormField(
              initialValue: c.apiKey,
              obscureText: true,
              decoration: const InputDecoration(labelText: 'API key (stays on this device)'),
              onChanged: (v) => c.apiKey = v.trim(),
            ),
          DropdownButtonFormField<String>(
            initialValue: c.safety,
            decoration: const InputDecoration(labelText: 'Safety'),
            items: const [
              DropdownMenuItem(value: 'ask', child: Text('ask — approve risky commands')),
              DropdownMenuItem(value: 'enforce', child: Text('enforce — block them')),
              DropdownMenuItem(value: 'off', child: Text('off')),
            ],
            onChanged: (v) => c.safety = v ?? 'ask',
          ),
        ]),
      ),
      actions: [
        FilledButton(
          style: FilledButton.styleFrom(backgroundColor: spideyRed),
          onPressed: () => Navigator.of(context).pop(),
          child: const Text('Save'),
        ),
      ],
    );
  }
}
