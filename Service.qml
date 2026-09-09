import QtQuick
import Quickshell.Io

Item {
  id: root
  property var shell: null
  readonly property bool running: worker.running
  readonly property bool bookRunning: bookWorker.running
  property string action: ""
  property string bookAction: ""
  property bool cancelling: false
  property bool bookCancelling: false
  readonly property bool cancelPending: cancelling || bookCancelling
  property real progressDone: 0
  property real progressTotal: 0
  readonly property int progressPercent: progressTotal > 0
    ? Math.max(0, Math.min(100, Math.round(progressDone * 100 / progressTotal)))
    : 0
  property string resultState: "idle"
  property var configData: null
  property var searchResults: []
  signal outputLine(string line)
  signal finished(int code, string action, bool cancelled)

  function backendScript() {
    return decodeURIComponent(Qt.resolvedUrl("backend.py").toString().replace(/^file:\/\//, ""))
  }

  function runTask(action, options) {
    if (action.indexOf("book-") === 0) return runBookTask(action, options)
    if (worker.running) return false
    root.action = action
    root.cancelling = false
    if (action === "download" || action === "book-download") {
      root.progressDone = 0
      root.progressTotal = 1
      root.resultState = "running"
    }
    worker.payload = JSON.stringify(Object.assign({}, options, {action: action}))
    worker.command = ["/usr/bin/python", "-B", "-u", backendScript()]
    worker.running = true
    return true
  }

  function runBookTask(action, options) {
    if (bookWorker.running) return false
    root.bookAction = action
    root.bookCancelling = false
    if (action === "book-download") {
      root.progressDone = 0
      root.progressTotal = 1
      root.resultState = "running"
    }
    bookWorker.payload = JSON.stringify(Object.assign({}, options, {action: action}))
    bookWorker.command = ["/usr/bin/python", "-B", "-u", backendScript()]
    bookWorker.running = true
    return true
  }

  function writeLine(value) {
    if (worker.running) {
      worker.write(value + "\n")
    }
  }

  function handleOutputLine(line) {
    if (line.indexOf("PROGRESS:") === 0) {
      try {
        const value = JSON.parse(line.slice(9))
        root.progressDone = Math.max(0, Number(value.done) || 0)
        root.progressTotal = Math.max(root.progressDone, Number(value.total) || 0)
      } catch (error) {}
      return
    }
    // yt-dlp reports a percentage in its normal progress lines rather
    // than the JSON byte counters used by the other download backends.
    if (root.action === "download") {
      const match = line.match(/^\s*\[download\]\s+([0-9]+(?:\.[0-9]+)?)%/)
      if (match) {
        const percent = Math.max(0, Math.min(100, Number(match[1]) || 0))
        root.progressDone = Math.round(percent)
        root.progressTotal = 100
      }
    }
    if (line.indexOf("CONFIG:") === 0) {
      try { root.configData = JSON.parse(line.slice(7)) } catch (error) {}
    } else if (line.indexOf("SEARCH:") === 0) {
      try { root.searchResults = JSON.parse(line.slice(7)) } catch (error) {}
    }
    root.outputLine(line)
  }

  function processExited(code, isBook) {
    if (isBook) {
      bookTerminateTimer.stop()
      bookKillTimer.stop()
    } else {
      terminateTimer.stop()
      killTimer.stop()
    }
    const completedAction = isBook ? root.bookAction : root.action
    const wasCancelled = (isBook ? root.bookCancelling : root.cancelling) || code === 130
    if (completedAction === "download" || completedAction === "book-download") {
      if (code === 0) root.progressDone = root.progressTotal
      root.resultState = wasCancelled ? "failed" : code === 0 ? "success" : "failed"
    }
    root.finished(code, completedAction, wasCancelled)
    if (isBook) root.bookCancelling = false
    else root.cancelling = false
  }

  function clearResult() {
    if (worker.running || bookWorker.running) return
    root.progressDone = 0
    root.progressTotal = 0
    root.resultState = "idle"
  }

  function cancel() {
    if ((!worker.running || root.cancelling) && (!bookWorker.running || root.bookCancelling)) return
    root.outputLine("Stopping current operation…")
    if (worker.running && !root.cancelling) {
      root.cancelling = true
      worker.signal(2)
      terminateTimer.restart()
    }
    if (bookWorker.running && !root.bookCancelling) {
      root.bookCancelling = true
      bookWorker.signal(2)
      bookTerminateTimer.restart()
    }
  }

  Timer {
    id: terminateTimer
    interval: 1200
    repeat: false
    onTriggered: {
      if (!worker.running) return
      root.outputLine("Operation did not stop; terminating it…")
      worker.signal(15)
      killTimer.restart()
    }
  }

  Timer {
    id: bookTerminateTimer
    interval: 1200
    repeat: false
    onTriggered: {
      if (!bookWorker.running) return
      root.outputLine("Book operation did not stop; terminating it…")
      bookWorker.signal(15)
      bookKillTimer.restart()
    }
  }

  Timer {
    id: bookKillTimer
    interval: 1200
    repeat: false
    onTriggered: {
      if (!bookWorker.running) return
      root.outputLine("Book operation did not terminate; forcing it to stop.")
      bookWorker.signal(9)
    }
  }

  Timer {
    id: killTimer
    interval: 1200
    repeat: false
    onTriggered: {
      if (!worker.running) return
      root.outputLine("Operation did not terminate; forcing it to stop.")
      worker.signal(9)
    }
  }

  Process {
    id: worker
    property string payload: ""
    stdinEnabled: true
    onStarted: { write(payload + "\n"); payload = "" }
    stdout: SplitParser { onRead: line => root.handleOutputLine(line) }
    stderr: SplitParser { onRead: line => root.outputLine(line) }
    onExited: root.processExited(code, false)
  }

  Process {
    id: bookWorker
    property string payload: ""
    stdinEnabled: true
    onStarted: { bookWorker.write(payload + "\n"); payload = "" }
    stdout: SplitParser { onRead: line => root.handleOutputLine(line) }
    stderr: SplitParser { onRead: line => root.outputLine(line) }
    onExited: root.processExited(code, true)
  }

  Component.onCompleted: runTask("config-load", {})
}
