// WebSocket client for the Spidey server — the Dart twin of web/src/useSpideySocket.js.
// Protocol (see spidey/server/app.py):
//   -> {"type":"start","task":...,"config":{...}} | {"type":"approval",...} | {"type":"stop"}
//   <- task_start / think / tool_call / tool_result / approval_request /
//      approval_result / finish / answer / error / max_steps / run_done

import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:web_socket_channel/web_socket_channel.dart';

enum MsgKind { user, think, tool, approval, finish, agent, error }

class ChatMsg {
  ChatMsg(this.kind, this.text, {this.tool, this.args, this.id, this.resolved});
  final MsgKind kind;
  String text;
  final String? tool;
  final String? args;
  final String? id; // approval id
  bool? resolved; // approvals: null = pending
  String status = 'running'; // tools: running | ok | err
}

class SpideyConfig {
  String serverUrl = 'http://127.0.0.1:8000';
  String provider = 'ollama';
  String model = '';
  String apiKey = '';
  String safety = 'ask';

  Map<String, dynamic> toJson() => {
        'provider': provider,
        'model': model,
        'api_key': apiKey,
        'safety': safety,
      };
}

class SpideyClient extends ChangeNotifier {
  final List<ChatMsg> messages = [];
  bool connected = false;
  bool running = false;
  ChatMsg? pendingApproval;
  String? lastSpoken; // set on answer/finish so the UI can TTS it once
  WebSocketChannel? _ch;

  Uri _wsUri(String serverUrl) {
    final u = Uri.parse(serverUrl);
    return u.replace(scheme: u.scheme == 'https' ? 'wss' : 'ws', path: '/ws');
  }

  void connect(String serverUrl) {
    _ch?.sink.close();
    connected = false;
    notifyListeners();
    final ch = WebSocketChannel.connect(_wsUri(serverUrl));
    _ch = ch;
    connected = true; // optimistic; errors flip it back
    ch.stream.listen(
      (data) => _onEvent(jsonDecode(data as String) as Map<String, dynamic>),
      onDone: () {
        if (_ch == ch) {
          connected = false;
          running = false;
          notifyListeners();
        }
      },
      onError: (_) {
        if (_ch == ch) {
          connected = false;
          running = false;
          notifyListeners();
        }
      },
    );
    notifyListeners();
  }

  void start(String task, SpideyConfig config) {
    messages.add(ChatMsg(MsgKind.user, task));
    running = true;
    _ch?.sink.add(jsonEncode({'type': 'start', 'task': task, 'config': config.toJson()}));
    notifyListeners();
  }

  void answerApproval(String id, bool approved) {
    _ch?.sink.add(jsonEncode({'type': 'approval', 'id': id, 'approved': approved}));
  }

  void stop() => _ch?.sink.add(jsonEncode({'type': 'stop'}));

  void _onEvent(Map<String, dynamic> ev) {
    switch (ev['type']) {
      case 'think':
        messages.add(ChatMsg(MsgKind.think, ev['text'] as String? ?? ''));
      case 'tool_call':
        messages.add(ChatMsg(MsgKind.tool, '',
            tool: ev['tool'] as String?, args: jsonEncode(ev['args'] ?? {})));
      case 'tool_result':
        final m = messages.lastWhere(
            (m) => m.kind == MsgKind.tool && m.status == 'running',
            orElse: () => ChatMsg(MsgKind.tool, ''));
        m.status = (ev['ok'] as bool? ?? true) ? 'ok' : 'err';
        m.text = ev['observation'] as String? ?? '';
      case 'approval_request':
        final m = ChatMsg(MsgKind.approval, ev['prompt'] as String? ?? '',
            id: ev['id'] as String?, resolved: null);
        messages.add(m);
        pendingApproval = m;
        lastSpoken = 'My spidey-sense is tingling — I need your approval. '
            'Tap approve or deny.';
      case 'approval_result':
        pendingApproval?.resolved = ev['approved'] as bool?;
        pendingApproval = null;
      case 'finish':
        messages.add(ChatMsg(MsgKind.finish, ev['summary'] as String? ?? ''));
        lastSpoken = ev['summary'] as String?;
      case 'answer':
        messages.add(ChatMsg(MsgKind.agent, ev['text'] as String? ?? ''));
        lastSpoken = ev['text'] as String?;
      case 'error':
        messages.add(ChatMsg(MsgKind.error, ev['message'] as String? ?? ''));
      case 'max_steps':
        messages.add(ChatMsg(MsgKind.error, 'Stopped: reached the step limit.'));
      case 'run_done':
        running = false;
        pendingApproval = null;
    }
    notifyListeners();
  }

  @override
  void dispose() {
    _ch?.sink.close();
    super.dispose();
  }
}
