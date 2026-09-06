import QtQuick
import Quickshell.Io

Item {
  id: root
  property var shell: null
  readonly property bool running: worker.running
  property string action: ""
  property bool cancelling: false
  property int progressDone: 0
  property int progressTotal: 0
  property string resultState: "idle"
  property var configData: null
  property var searchResults: []
  signal outputLine(string line)
  signal finished(int code, string action, bool cancelled)

  function runTask(action, options) {
    if (worker.running) return false
    root.action = action
    root.cancelling = false
    if (action === "download") {
      root.progressDone = 0
      root.progressTotal = 1
      root.resultState = "running"
    }
    const script = decodeURIComponent(Qt.resolvedUrl("backend.py").toString().replace(/^file:\/\//, ""))
    worker.payload = JSON.stringify(Object.assign({}, options, {action: action}))
    worker.command = ["/usr/bin/python", "-B", "-u", script]
    worker.running = true
    return true
  }

  function writeLine(value) {
    if (worker.running) {
      worker.write(value + "\n")
    }
  }

  function clearResult() {
    if (worker.running) return
    root.progressDone = 0
    root.progressTotal = 0
    root.resultState = "idle"
  }

  function cancel() {
    if (!worker.running || root.cancelling) return
    root.cancelling = true
    root.outputLine("Stopping current operation…")
    worker.signal(2)
    terminateTimer.restart()
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
    stdout: SplitParser {
      onRead: line => {
        if (line.indexOf("PROGRESS:") === 0) {
          try {
            const value = JSON.parse(line.slice(9))
            root.progressDone = Math.max(0, Number(value.done) || 0)
            root.progressTotal = Math.max(root.progressDone, Number(value.total) || 0)
          } catch (error) {}
          return
        }
        if (line.indexOf("CONFIG:") === 0) {
          try { root.configData = JSON.parse(line.slice(7)) } catch (error) {}
        } else if (line.indexOf("SEARCH:") === 0) {
          try { root.searchResults = JSON.parse(line.slice(7)) } catch (error) {}
        }
        root.outputLine(line)
      }
    }
    stderr: SplitParser { onRead: line => root.outputLine(line) }
    onExited: function(code) {
      terminateTimer.stop()
      killTimer.stop()
      const completedAction = root.action
      const wasCancelled = root.cancelling || code === 130
      if (completedAction === "download") {
        if (code === 0) root.progressDone = root.progressTotal
        root.resultState = wasCancelled ? "failed" : code === 0 ? "success" : "failed"
      }
      root.finished(code, completedAction, wasCancelled)
      root.cancelling = false
    }
  }

  Component.onCompleted: runTask("config-load", {})
}
