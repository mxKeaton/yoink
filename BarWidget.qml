import QtQuick
import Quickshell
import qs.Commons
import qs.Ui

Panel {
  id: root
  moduleName: "denis.yoink"
  ipcTarget: "denis.yoink"
  implicitWidth: icon.implicitWidth
  implicitHeight: icon.implicitHeight

  readonly property var downloadService: bar && bar.shell ? bar.shell.serviceFor("denis.yoink") : null
  readonly property bool workerRunning: downloadService ? downloadService.running : false

  property bool configuring: false
  property bool games: false
  property var gameResults: []
  property var selectedGame: null
  property string gameStatus: "Browse trending games or search the catalogue."
  property string gameDebug: ""
  property var gameSources: []
  property bool gameSourcesLoading: false
  Timer { id: gameSourcesTimer; interval: 0; repeat: false; onTriggered: if (root.selectedGame) root.gameTask("game-sources", {name: root.selectedGame.name}) }
  property int gamePage: 1
  property bool gameBrowsingTrending: true
  property bool searching: false
  property var searchResults: []
  property var selectedSong: null
  readonly property bool musicInput: searching ? selectedSong !== null : spotifyLink
  readonly property bool inputReady: searching ? selectedSong !== null : link.text.trim() !== ""
  property string musicSource: "qobuz"
  property string musicCodec: "original"
  property int musicQuality: 3
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

  function sourceLabel(url) {
    const name = String(url || "").replace(/^https?:\/\//, "").replace(/^www\./, "").split("/")[0].split(".")[0]
    return name.replace(/[-_]+/g, " ").replace(/\b\w/g, function(letter) { return letter.toUpperCase() })
  }

  function appendLog(line) {
    if (line.indexOf("CONFIG:") === 0) {
      try { configForm.apply(JSON.parse(line.slice(7))) } catch (e) {}
      return
    }
    if (line.indexOf("SEARCH:") === 0) {
      try { root.searchResults = JSON.parse(line.slice(7)) } catch (e) { root.status = "Could not read search results." }
      return
    }
    if (line.indexOf("GAMES:") === 0) {
      try { root.gameResults = JSON.parse(line.slice(6)); root.gameStatus = root.gameResults.length ? "Select a game to view details." : "No games found." } catch (e) { root.gameStatus = "Could not read game results." }
      return
    }
    if (line.indexOf("GAME_DETAIL:") === 0) {
      try { root.selectedGame = JSON.parse(line.slice(12)); root.gameStatus = "Game details loaded." } catch (e) { root.gameStatus = "Could not read game details." }
      return
    }
    if (line.indexOf("GAME_SOURCES:") === 0) {
      try { root.gameSources = JSON.parse(line.slice(13)); root.gameSourcesLoading = false; root.gameStatus = root.gameSources.length ? "Matching game websites found." : "No configured website matched this title." } catch (e) { root.gameSources = []; root.gameSourcesLoading = false }
      return
    }
    if (line.indexOf("GAME_DEBUG:") === 0) {
      root.gameDebug = line.slice(11)
      return
    }
    if (line.indexOf("OPEN:") === 0) {
      const url = line.slice(5)
      if (url.indexOf("https://accounts.spotify.com/") === 0) {
        Quickshell.execDetached(["omarchy-launch-browser", url])
        root.status = "Finish connecting Spotify in your browser."
      }
      return
    }
    logText = (logText + line + "\n").slice(-16000)
    if (line.indexOf("[download]") === 0) status = line
  }

  function clearDownload() {
    if (root.workerRunning) return
    link.text = ""
    query.text = ""
    searchResults = []
    selectedSong = null
    gameResults = []
    selectedGame = null
    gamePage = 1
    gameBrowsingTrending = true
    gameDebug = ""
    gameSources = []
    gameSourcesLoading = false
    logText = ""
    status = "Paste a link or search for a song to get started."
    cancelling = false
    configuring = false
    if (root.downloadService) root.downloadService.clearResult()
    scroll.contentY = 0
    if (searching) query.forceActiveFocus(); else link.forceActiveFocus()
  }

  function start(action) {
    if (root.workerRunning) return
    root.action = action
    root.cancelling = false
    root.logText = ""
    root.status = action === "formats" ? "Fetching available formats…" : "Starting download…"
    const options = {url: link.text, mode: mode, action: action,
      format: mode === "Video" ? videoFormat : audioFormat,
      quality: mode === "Video" ? videoQuality : audioQuality,
      output: destination.text, metadata: metadata, subtitles: mode === "Video" && subtitles,
      selection: searching ? selectedSong : null, source: musicSource, musicCodec: musicCodec, musicQuality: musicQuality}
    runTask(action, options)
  }

  function gameTask(action, options) {
    if (root.workerRunning || !root.downloadService) return
    root.gameStatus = action === "game-search" ? "Searching games…" : action === "game-sources" ? "Checking game websites…" : "Loading game catalogue…"
    root.runTask(action, options)
  }

  function beginGameSearch(value) {
    const text = String(value || "").trim()
    if (!text) return
    root.selectedGame = null
    root.gameSources = []
    root.gameSourcesLoading = false
    root.gamePage = 1
    root.gameBrowsingTrending = false
    root.gameTask("game-search", {query: text})
  }

  function runTask(action, options) {
    if (root.workerRunning || !root.downloadService) return
    root.action = action
    root.cancelling = false
    if (action !== "config-load") root.logText = ""
    root.status = action === "config-load" ? root.status : "Working…"
    root.downloadService.runTask(action, options)
  }

  function workerExited(code, completedAction, wasCancelled) {
      root.cancelling = false
      if (completedAction === "config-load" && code === 0) return
      if (completedAction === "game-detail" && root.selectedGame) {
        root.gameSourcesLoading = true
        gameSourcesTimer.restart()
      }
      root.status = wasCancelled ? "Cancelled."
        : code === 2 ? "Some tracks could not be completed. See the report below."
        : code !== 0 ? "Failed — see details below."
        : completedAction === "formats" ? "Available formats listed below."
        : completedAction === "search" ? (root.searchResults.length ? "Select a song below." : "No songs found. Try adding the artist name.")
      : completedAction === "download" ? "Download complete." : completedAction.indexOf("game-") === 0 ? root.gameStatus : "Configuration updated."
  }

  Connections {
    target: root.downloadService
    function onOutputLine(line) { root.appendLog(line) }
    function onFinished(code, completedAction, wasCancelled) { root.workerExited(code, completedAction, wasCancelled) }
    function onConfigDataChanged() {
      if (root.downloadService && root.downloadService.configData) configForm.apply(root.downloadService.configData)
    }
    function onSearchResultsChanged() {
      if (root.downloadService) root.searchResults = root.downloadService.searchResults
    }
  }

  onDownloadServiceChanged: {
    if (!root.downloadService) return
    if (root.downloadService.configData) configForm.apply(root.downloadService.configData)
    root.searchResults = root.downloadService.searchResults
  }

  BarIconButton {
    id: icon
    anchors.fill: parent
    bar: root.bar
    text: "\uf019"
    slotSize: Style.bar.statusSlot
    fontSize: Style.font.caption
    foreground: root.downloadService && root.downloadService.resultState === "success" ? Color.accent
      : root.downloadService && root.downloadService.resultState === "failed" ? Color.urgent
      : root.bar ? root.bar.barForeground : Color.foreground
    tooltipText: root.workerRunning ? root.status : "Yoink"
    onPressed: root.toggle()
  }

  Rectangle {
    id: progressBadge
    z: 3
    visible: root.downloadService && root.downloadService.progressTotal > 0
    anchors.right: parent.right
    anchors.top: parent.top
    width: Math.max(height, badgeText.implicitWidth + Style.space(4))
    height: Math.max(10, Style.font.bodySmall + Style.space(2))
    radius: height / 2
    color: root.downloadService && root.downloadService.resultState === "failed" ? Color.urgent
      : root.downloadService && root.downloadService.resultState === "success" ? Color.accent
      : Color.bar.background
    border.width: 1
    border.color: root.bar ? root.bar.barForeground : Color.foreground
    Text {
      id: badgeText
      anchors.centerIn: parent
      text: root.downloadService ? root.downloadService.progressDone + "/" + root.downloadService.progressTotal : ""
      color: root.downloadService && root.downloadService.resultState === "failed" ? Color.background
        : root.downloadService && root.downloadService.resultState === "success" ? Color.background
        : root.bar ? root.bar.barForeground : Color.foreground
      font.family: Style.font.family
      font.pixelSize: Math.max(7, Style.font.bodySmall * 0.72)
      font.bold: true
    }
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
    enabled: !root.workerRunning
  }

  KeyboardPanel {
    id: popup
    anchorItem: icon
    owner: root
    bar: root.bar
    open: root.opened
    focusTarget: root.configuring ? configForm : root.games ? gameQuery : link
    contentWidth: fittedContentWidth(Style.space(620))
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
            Label { text: "Yoink"; font.pixelSize: Style.font.title; width: parent.width - clearButton.width - closeButton.width }
            Button {
              id: clearButton
              text: "Clear"
              tooltipText: "Clear the link and progress log"
              enabled: !root.workerRunning
              focusable: true
              onClicked: root.clearDownload()
            }
            Button { id: closeButton; text: "✕"; focusable: true; onClicked: root.close() }
          }
          Flow {
            width: parent.width; spacing: Style.space(6)
            Button { text: "Music"; selected: !root.configuring && !root.games; focusable: true; onClicked: { root.games = false; root.configuring = false } }
            Button { text: "Games"; selected: root.games; focusable: true; onClicked: { root.games = true; root.configuring = false; root.selectedGame = null; root.gameTask("game-trending", {}) } }
            Button { text: "Configuration"; selected: root.configuring; focusable: true; onClicked: { root.games = false; root.configuring = true } }
          }
          Configuration {
            id: configForm
            width: parent.width
            visible: root.configuring && !root.games
            busy: root.workerRunning
            onRequested: (action, payload) => root.runTask(action, payload)
          }
          Column {
            id: gamesView
            visible: root.games && !root.configuring
            width: parent.width
            spacing: Style.space(10)
            Label { text: "Game browser"; font.pixelSize: Style.font.title }
            TextField {
              id: gameQuery
              width: parent.width
              placeholderText: "Search games…"
              enabled: !root.workerRunning
              selectByMouse: true
              onAccepted: root.beginGameSearch(text)
            }
            Flow {
              width: parent.width; spacing: Style.space(6)
              Choice { text: "Search"; enabled: !root.workerRunning && gameQuery.text.trim() !== ""; onClicked: root.beginGameSearch(gameQuery.text) }
              Choice { text: "Trending"; enabled: !root.workerRunning; onClicked: { root.gamePage = 1; root.gameBrowsingTrending = true; root.gameTask("game-trending", {page: 1}) } }
            }
            Label { text: root.gameStatus; font.pixelSize: Style.font.bodySmall }
            Flow {
              visible: root.selectedGame === null && root.gameBrowsingTrending
              width: parent.width; spacing: Style.space(6)
              Choice { text: "‹ Previous"; enabled: !root.workerRunning && root.gamePage > 1; onClicked: { root.gamePage -= 1; root.gameTask("game-trending", {page: root.gamePage}) } }
              Label { text: "Trending page " + root.gamePage; font.pixelSize: Style.font.bodySmall }
              Choice { text: "Next ›"; enabled: !root.workerRunning && root.gamePage < 5 && root.gameResults.length > 0; onClicked: { root.gamePage += 1; root.gameTask("game-trending", {page: root.gamePage}) } }
            }
            Grid {
              visible: root.selectedGame === null
              width: parent.width
              columns: 3
              columnSpacing: Style.space(8); rowSpacing: Style.space(8)
              Repeater {
                model: root.gameResults
                Rectangle {
                  required property var modelData
                  width: (gamesView.width - Style.space(24)) / 3
                  height: width * 430 / 920
                  radius: 0
                  color: Color.background
                  border.color: cardMouse.containsMouse ? Color.accent : Color.foreground
                  border.width: 1
                  property bool triedBackup: false
                  Image {
                    id: coverImage; anchors.fill: parent; anchors.margins: 1; fillMode: Image.PreserveAspectFit
                    source: modelData.cover || ""; visible: status === Image.Ready; asynchronous: true
                    onStatusChanged: if (status === Image.Error && !parent.triedBackup && modelData.backupCover !== "") { parent.triedBackup = true; source = modelData.backupCover }
                  }
                  Label {
                    anchors.centerIn: parent
                    width: parent.width - Style.space(12)
                    horizontalAlignment: Text.AlignHCenter
                    text: modelData.name
                    visible: coverImage.status !== Image.Ready
                    font.pixelSize: Style.font.bodySmall
                    color: cardMouse.containsMouse ? Color.background : Color.foreground
                  }
                  MouseArea { id: cardMouse; anchors.fill: parent; hoverEnabled: true; onClicked: { root.selectedGame = modelData; root.gameTask("game-detail", {id: modelData.id, source: modelData.source}) } }
                }
              }
            }
            Column {
              visible: root.selectedGame !== null
              width: parent.width; spacing: Style.space(8)
              Button { text: "← Back to games"; focusable: true; onClicked: root.selectedGame = null }
              Image { width: parent.width; height: Style.space(270); fillMode: Image.PreserveAspectFit; source: root.selectedGame ? root.selectedGame.cover : ""; asynchronous: true; visible: source !== "" }
              Label { text: root.selectedGame ? root.selectedGame.name : ""; font.pixelSize: Style.font.subtitle }
              Label { text: root.selectedGame ? root.selectedGame.summary : ""; width: parent.width; font.pixelSize: Style.font.bodySmall }
              Label { text: root.selectedGame ? ((root.selectedGame.genres || []).join(" · ") + (root.selectedGame.rating ? "\nRating " + root.selectedGame.rating + "/100" : "")) : ""; font.pixelSize: Style.font.bodySmall }
              Flow {
                spacing: Style.space(6)
                Repeater {
                  model: root.gameSources
                  Choice { required property var modelData; text: "Open " + root.sourceLabel(modelData.base); onClicked: Quickshell.execDetached(["omarchy-launch-browser", modelData.url]) }
                }
                Choice { text: "Open Steam"; onClicked: if (root.selectedGame) Quickshell.execDetached(["omarchy-launch-browser", "https://store.steampowered.com/app/" + root.selectedGame.id]) }
              }
              Label { visible: root.gameSourcesLoading; text: "Checking configured game websites…"; font.pixelSize: Style.font.bodySmall }
              Label { visible: root.gameDebug !== ""; text: "Debug · " + root.gameDebug; width: parent.width; font.pixelSize: Style.font.bodySmall; color: Color.foreground; opacity: 0.7; elide: Text.ElideRight }
            }
          }
          Column {
            width: parent.width
            spacing: Style.space(12)
            visible: !root.configuring && !root.games
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
              enabled: !root.workerRunning
              selectByMouse: true
              onTextEdited: { root.selectedSong = null; root.searchResults = [] }
              onAccepted: if (!root.workerRunning && text.trim()) root.runTask("search", {query: text})
            }
            Choice {
              text: "Search"
              enabled: !root.workerRunning && query.text.trim() !== ""
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
                    enabled: !root.workerRunning
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
            enabled: !root.workerRunning
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
            Label { text: "Preferred source" }
            Flow {
              width: parent.width; spacing: Style.space(6)
              Repeater {
                model: ["qobuz", "deezer", "tidal"]
                Choice {
                  required property string modelData
                  text: modelData.charAt(0).toUpperCase() + modelData.slice(1)
                  selected: root.musicSource === modelData
                  onClicked: root.musicSource = modelData
                }
              }
            }
            Label {
              width: parent.width
              text: "Yoink tries this service first, then your other configured services. YouTube Music is always the last resort."
              font.pixelSize: Style.font.bodySmall
            }
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
            placeholderText: root.searching || root.musicInput ? "~/Downloads/Yoink/Music" : "~/Downloads/Yoink/" + root.mode
            enabled: !root.workerRunning
            selectByMouse: true
          }
          Flow {
            width: parent.width; spacing: Style.space(6)
            Choice { text: root.searching || root.musicInput ? "Download music" : "Download " + root.mode.toLowerCase(); enabled: !root.workerRunning && root.inputReady; onClicked: root.start("download") }
            Choice { visible: !root.musicInput; text: "Available formats"; enabled: !root.workerRunning && root.inputReady; onClicked: root.start("formats") }
          }
          }
          Button {
            visible: root.workerRunning
            text: root.downloadService && root.downloadService.cancelling ? "Stopping…" : "Cancel"
            focusable: true
            enabled: root.downloadService && !root.downloadService.cancelling
            onClicked: if (root.downloadService) root.downloadService.cancel()
          }
          Label { width: parent.width; text: root.status }
          Label { visible: root.workerRunning; width: parent.width; text: "You can close this popup while the download continues."; font.pixelSize: Style.font.bodySmall }
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
