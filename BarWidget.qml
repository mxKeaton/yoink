import QtQuick
import Quickshell.Io
import qs.Commons
import qs.Ui

Panel {
  id: root
  moduleName: "denis.yoinker"
  ipcTarget: "denis.yoinker"
  implicitWidth: icon.implicitWidth
  implicitHeight: icon.implicitHeight

  property bool configuring: false
  property bool searching: false
  property var searchResults: []
  property var selectedSong: null
  readonly property bool musicInput: searching ? selectedSong !== null : spotifyLink
  readonly property bool inputReady: searching ? selectedSong !== null : link.text.trim() !== ""
  property string musicSource: "qobuz"
  property string musicCodec: "original"
  property int musicQuality: 3
  property bool fallback: false
  readonly property bool spotifyLink: link.text.indexOf("open.spotify.com") !== -1 || link.text.indexOf("spotify:") === 0
  property string mode: "Video"
  property string videoFormat: "auto"
  property string audioFormat: "best"
  property string videoQuality: "Best"
  property string audioQuality: "0"
  property bool metadata: false
  property bool subtitles: false
  property string status: "Paste a link or search for a song to get started."
  property string logText: ""
  property bool cancelling: false
  property string action: "download"

  function appendLog(line) {
    if (line.indexOf("CONFIG:") === 0) {
      try { configForm.apply(JSON.parse(line.slice(7))) } catch (e) {}
      return
    }
    if (line.indexOf("SEARCH:") === 0) {
      try { root.searchResults = JSON.parse(line.slice(7)) } catch (e) { root.status = "Could not read search results." }
      return
    }
    logText = (logText + line + "\n").slice(-16000)
    if (line.indexOf("[download]") === 0) status = line
  }

  function clearDownload() {
    if (worker.running) return
    link.text = ""
    query.text = ""
    searchResults = []
    selectedSong = null
    logText = ""
    status = "Paste a link or search for a song to get started."
    cancelling = false
    configuring = false
    scroll.contentY = 0
    if (searching) query.forceActiveFocus(); else link.forceActiveFocus()
  }

  function start(action) {
    if (worker.running) return
    root.action = action
    root.cancelling = false
    root.logText = ""
    root.status = action === "formats" ? "Fetching available formats…" : "Starting download…"
    const options = {url: link.text, mode: mode, action: action,
      format: mode === "Video" ? videoFormat : audioFormat,
      quality: mode === "Video" ? videoQuality : audioQuality,
      output: destination.text, metadata: metadata, subtitles: mode === "Video" && subtitles,
      selection: searching ? selectedSong : null, source: musicSource, musicCodec: musicCodec, musicQuality: musicQuality, fallback: fallback}
    runTask(action, options)
  }

  function runTask(action, options) {
    if (worker.running) return
    root.action = action
    root.cancelling = false
    if (action !== "config-load") root.logText = ""
    root.status = action === "config-load" ? root.status : "Working…"
    const script = decodeURIComponent(Qt.resolvedUrl("backend.py").toString().replace(/^file:\/\//, ""))
    worker.payload = JSON.stringify(Object.assign({}, options, {action: action}))
    worker.command = ["/usr/bin/python", "-B", "-u", script]
    worker.running = true
  }

  Component.onCompleted: runTask("config-load", {})

  Process {
    id: worker
    property string payload: ""
    stdinEnabled: true
    onStarted: { write(payload + "\n"); payload = "" }
    stdout: SplitParser { onRead: line => root.appendLog(line) }
    stderr: SplitParser { onRead: line => root.appendLog(line) }
    onExited: function(code) {
      if (root.action === "config-load" && code === 0) return
      root.status = root.cancelling ? "Cancelled."
        : code === 2 ? "Some tracks could not be completed. See the report below."
        : code !== 0 ? "Failed — see details below."
        : root.action === "formats" ? "Available formats listed below."
        : root.action === "search" ? (root.searchResults.length ? "Select a song below." : "No songs found. Try adding the artist name.")
        : root.action === "match" ? "Matching complete. See details below."
        : root.action === "download" ? "Download complete." : "Configuration updated."
    }
  }

  BarIconButton {
    id: icon
    anchors.fill: parent
    bar: root.bar
    text: "\uf019"
    slotSize: Style.bar.statusSlot
    fontSize: Style.font.caption
    tooltipText: worker.running ? root.status : "Yoinker"
    onPressed: root.toggle()
  }

  component Label: Text {
    color: Color.foreground
    font.family: Style.font.family
    font.pixelSize: Style.font.body
    textFormat: Text.PlainText
    wrapMode: Text.Wrap
  }

  component Choice: Button {
    focusable: true
    bordered: true
    enabled: !worker.running
  }

  KeyboardPanel {
    id: popup
    anchorItem: icon
    owner: root
    bar: root.bar
    open: root.opened
    focusTarget: root.configuring ? configForm : link
    contentWidth: fittedContentWidth(Style.space(480))
    contentHeight: fittedContentHeight(form.implicitHeight)

    Item {
      anchors.fill: parent
      Keys.onEscapePressed: root.close()

      Flickable {
        id: scroll
        anchors.fill: parent
        clip: true
        contentHeight: form.implicitHeight
        contentWidth: width
        boundsBehavior: Flickable.StopAtBounds

        Column {
          id: form
          width: scroll.width
          spacing: Style.space(12)

          Row {
            width: parent.width
            Label { text: "Yoinker"; font.pixelSize: Style.font.title; width: parent.width - clearButton.width - closeButton.width }
            Button {
              id: clearButton
              text: "Clear"
              tooltipText: "Clear the link and progress log"
              enabled: !worker.running
              focusable: true
              onClicked: root.clearDownload()
            }
            Button { id: closeButton; text: "✕"; focusable: true; onClicked: root.close() }
          }
          Flow {
            width: parent.width; spacing: Style.space(6)
            Button { text: "Download"; selected: !root.configuring; focusable: true; onClicked: root.configuring = false }
            Button { text: "Configuration"; selected: root.configuring; focusable: true; onClicked: root.configuring = true }
          }
          Configuration {
            id: configForm
            width: parent.width
            visible: root.configuring
            busy: worker.running
            onRequested: (action, payload) => root.runTask(action, payload)
          }
          Column {
            width: parent.width
            spacing: Style.space(12)
            visible: !root.configuring
          Flow {
            width: parent.width; spacing: Style.space(6)
            Choice { text: "Paste link"; selected: !root.searching; onClicked: root.searching = false }
            Choice { text: "Search titles"; selected: root.searching; onClicked: { root.searching = true; query.forceActiveFocus() } }
          }
          Label { visible: !root.searching; text: "YouTube / Spotify song, playlist, album or artist" }
          Label {
            visible: !root.searching && /spotify.*[/:]artist[/:]/.test(link.text)
            width: parent.width
            text: "Artist links include albums and singles; repeated track IDs are skipped."
            font.pixelSize: Style.font.bodySmall
          }
          Column {
            visible: root.searching
            width: parent.width
            spacing: Style.space(8)
            Label { text: "Find a song · YouTube Music catalog" }
            TextField {
              id: query
              width: parent.width
              placeholderText: "Song title or artist and title…"
              enabled: !worker.running
              selectByMouse: true
              onTextEdited: { root.selectedSong = null; root.searchResults = [] }
              onAccepted: if (!worker.running && text.trim()) root.runTask("search", {query: text})
            }
            Choice {
              text: "Search"
              enabled: !worker.running && query.text.trim() !== ""
              onClicked: { root.selectedSong = null; root.searchResults = []; root.runTask("search", {query: query.text}) }
            }
            Flickable {
              visible: root.searchResults.length > 0
              width: parent.width
              height: Math.min(resultsColumn.implicitHeight, Style.space(220))
              contentWidth: width
              contentHeight: resultsColumn.implicitHeight
              clip: true
              Column {
                id: resultsColumn
                width: parent.width
                spacing: Style.space(4)
                Repeater {
                  model: root.searchResults
                  Button {
                    required property var modelData
                    width: parent.width
                    height: resultLabel.implicitHeight + Style.space(16)
                    Label {
                      id: resultLabel
                      anchors.left: parent.left
                      anchors.leftMargin: Style.space(10)
                      anchors.verticalCenter: parent.verticalCenter
                      width: parent.width - Style.space(20)
                      text: modelData.title + "\n" + modelData.artists.join(", ") + " · " + modelData.durationLabel + (modelData.album ? "\n" + modelData.album : "")
                    }
                    selected: root.selectedSong !== null && root.selectedSong.videoId === modelData.videoId
                    enabled: !worker.running
                    leftAlign: true
                    focusable: true
                    bordered: true
                    onClicked: root.selectedSong = modelData
                  }
                }
              }
            }
            Label {
              visible: root.selectedSong !== null
              width: parent.width
              text: root.selectedSong ? "Selected: " + root.selectedSong.title + " — " + root.selectedSong.artists.join(", ") : ""
            }
          }
          TextField {
            id: link
            visible: !root.searching
            width: parent.width
            placeholderText: "Paste a YouTube or Spotify link…"
            enabled: !worker.running
            selectByMouse: true
          }
          Flow {
            visible: !root.searching && !root.spotifyLink
            width: parent.width; spacing: Style.space(6)
            Repeater {
              model: ["Video", "Audio"]
              Choice { required property string modelData; text: modelData; selected: root.mode === modelData; onClicked: root.mode = modelData }
            }
          }
          Label { visible: !root.searching && !root.spotifyLink; text: root.mode === "Video" ? "Video quality · maximum height" : "Audio quality · encoding bitrate" }
          Flow {
            width: parent.width; spacing: Style.space(6)
            Repeater {
              model: root.searching || root.spotifyLink ? [] : root.mode === "Video" ? ["Best", "2160", "1440", "1080", "720", "480"] : ["0", "192K", "256K", "320K"]
              Choice {
                required property string modelData
                text: modelData === "0" ? "Best" : modelData
                selected: modelData === (root.mode === "Video" ? root.videoQuality : root.audioQuality)
                onClicked: { if (root.mode === "Video") root.videoQuality = modelData; else root.audioQuality = modelData }
              }
            }
          }
          Label { visible: !root.searching && !root.spotifyLink; text: root.mode === "Video" ? "Video container" : "Audio format" }
          Flow {
            width: parent.width; spacing: Style.space(6)
            Repeater {
              model: root.searching || root.spotifyLink ? [] : root.mode === "Video" ? ["auto", "mkv", "mp4"] : ["best", "mp3", "m4a", "opus", "flac", "wav"]
              Choice {
                required property string modelData
                text: modelData === "best" ? "Original" : modelData.toUpperCase()
                selected: modelData === (root.mode === "Video" ? root.videoFormat : root.audioFormat)
                onClicked: { if (root.mode === "Video") root.videoFormat = modelData; else root.audioFormat = modelData }
              }
            }
          }
          Flow {
            width: parent.width; spacing: Style.space(6)
            visible: !root.searching && !root.spotifyLink
            Choice { text: "Metadata"; selected: root.metadata; onClicked: root.metadata = !root.metadata }
            Choice { visible: root.mode === "Video"; text: "English subtitles"; selected: root.subtitles; onClicked: root.subtitles = !root.subtitles }
          }
          Column {
            visible: root.musicInput
            width: parent.width
            spacing: Style.space(10)
            Label { text: "Download music from" }
            Flow {
              width: parent.width; spacing: Style.space(6)
              Repeater {
                model: ["qobuz", "deezer", "tidal", "youtube"]
                Choice {
                  required property string modelData
                  text: modelData === "youtube" ? "YouTube Music" : modelData.charAt(0).toUpperCase() + modelData.slice(1)
                  selected: root.musicSource === modelData
                  onClicked: root.musicSource = modelData
                }
              }
            }
            Choice { text: "Try other configured sources if needed"; selected: root.fallback; onClicked: root.fallback = !root.fallback }
            Label { text: "Quality · limited by source and account" }
            Flow {
              width: parent.width; spacing: Style.space(6)
              Repeater {
                model: ["Lossy", "CD", "Hi-res", "Maximum"]
                Choice { required property string modelData; required property int index; text: modelData; selected: root.musicQuality === index + 1; onClicked: root.musicQuality = index + 1 }
              }
            }
            Label { text: "Output format" }
            Flow {
              width: parent.width; spacing: Style.space(6)
              Repeater {
                model: ["original", "flac", "mp3", "opus"]
                Choice { required property string modelData; text: modelData.toUpperCase(); selected: root.musicCodec === modelData; onClicked: root.musicCodec = modelData }
              }
            }
          }
          Label { text: "Save to" }
          TextField {
            id: destination
            width: parent.width
            placeholderText: root.searching || root.musicInput ? "~/Downloads/Yoinker/Music" : "~/Downloads/Yoinker/" + root.mode
            enabled: !worker.running
            selectByMouse: true
          }
          Flow {
            width: parent.width; spacing: Style.space(6)
            Choice { text: root.searching || root.musicInput ? "Download music" : "Download " + root.mode.toLowerCase(); enabled: !worker.running && root.inputReady; onClicked: root.start("download") }
            Choice { text: root.musicInput ? "Match tracks" : "Available formats"; enabled: !worker.running && root.inputReady; onClicked: root.start(root.musicInput ? "match" : "formats") }
          }
          }
          Button {
            visible: worker.running
            text: root.cancelling ? "Stopping…" : "Cancel"
            focusable: true
            enabled: !root.cancelling
            onClicked: { root.cancelling = true; worker.signal(2) }
          }
          Label { width: parent.width; text: root.status }
          Label { visible: worker.running; width: parent.width; text: "You can close this popup while the download continues."; font.pixelSize: Style.font.bodySmall }
          Flickable {
            visible: root.logText !== ""
            width: parent.width
            height: visible ? Style.space(140) : 0
            clip: true
            contentWidth: width
            contentHeight: details.implicitHeight
            onContentHeightChanged: contentY = Math.max(0, contentHeight - height)
            TextEdit {
              id: details
              width: parent.width
              text: root.logText
              readOnly: true
              selectByMouse: true
              wrapMode: TextEdit.Wrap
              textFormat: TextEdit.PlainText
              color: Color.foreground
              font.family: Style.font.family
              font.pixelSize: Style.font.bodySmall
            }
          }
        }
      }
    }
  }
}
