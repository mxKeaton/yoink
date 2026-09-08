import QtQuick
import Quickshell
import qs.Commons
import qs.Ui

Column {
  id: root
  spacing: Style.space(10)
  property bool busy: false
  property string platform: "spotify"
  property var saved: ({})
  property var edits: ({})
  readonly property string qobuzMode: edits.qobuz_auth_mode || saved.qobuz_auth_mode || "password"
  signal requested(string action, var payload)

  function apply(values) {
    saved = values
    edits = ({})
  }
  function fields() {
    const definitions = {
      spotify: [ ["spotify_client_id", "Spotify app client ID", false] ],
      qobuz: (root.qobuzMode === "password"
        ? [ ["qobuz_email", "Username / email (Qobuz account email)", false], ["qobuz_password", "Password", true] ]
        : [ ["qobuz_user_id", "User ID", false], ["qobuz_token", "User auth token (required)", true],
            ["qobuz_app_id", "App ID", false], ["qobuz_app_secret", "App Secret", true] ]),
      deezer: [ ["deezer_arl", "Your account’s ARL cookie", true] ],
      tidal: [ ["tidal_user_id", "User ID", false], ["tidal_country_code", "Country code (e.g. DE)", false],
        ["tidal_access_token", "Access token", true], ["tidal_refresh_token", "Refresh token", true],
        ["tidal_token_expiry", "Token expiry (Unix timestamp)", false] ],
      youtube: [ ["youtube_cookies", "Optional Netscape cookies file path", false] ],
    }
    return definitions[platform]
  }

  Flow {
    width: parent.width
    spacing: Style.space(4)
    Repeater {
      model: ["spotify", "qobuz", "deezer", "tidal", "youtube"]
      Button {
        required property string modelData
        text: modelData === "youtube" ? "YT Music" : modelData.charAt(0).toUpperCase() + modelData.slice(1)
        selected: root.platform === modelData
        enabled: !root.busy
        focusable: true
        onClicked: root.platform = modelData
      }
    }
  }
  Text {
    width: parent.width
    color: Color.foreground
    font.family: Style.font.family
    font.pixelSize: Style.font.bodySmall
    wrapMode: Text.Wrap
    textFormat: Text.PlainText
    text: root.platform === "spotify"
      ? "Create a Spotify app and register this redirect URI:\nhttp://127.0.0.1:8765/callback\nSave your client ID, then connect in your browser.\n" + (root.saved.spotify_connected ? "Spotify is connected." : "Spotify is not connected.")
      : root.platform === "qobuz" ? (root.qobuzMode === "password" ? "Sign in with your Qobuz account email and password." : "User ID login requires a user auth token. App ID and App Secret identify the app, not your account.")
      : root.platform === "deezer" ? "Enter the ARL cookie from your own Deezer account."
      : root.platform === "tidal" ? "Connect in your browser, or enter an existing Tidal session below."
      : "YouTube Music search works without login. A cookies file is optional for downloads."
  }
  Button {
    visible: root.platform === "spotify"
    text: "Create Spotify app ↗"
    enabled: !root.busy
    focusable: true
    bordered: true
    onClicked: Quickshell.execDetached(["omarchy-launch-browser", "https://developer.spotify.com/dashboard/create"])
  }
  Flow {
    visible: root.platform === "qobuz"
    width: parent.width
    spacing: Style.space(6)
    Repeater {
      model: ["password", "token"]
      Button {
        required property string modelData
        text: modelData === "password" ? "Username / Password" : "User ID / App ID / App Secret"
        selected: root.qobuzMode === modelData
        enabled: !root.busy
        focusable: true
        bordered: true
        onClicked: root.edits = Object.assign({}, root.edits, {qobuz_auth_mode: modelData})
      }
    }
  }
  Repeater {
    model: root.fields()
    Column {
      required property var modelData
      width: root.width
      spacing: Style.space(4)
      Text {
        text: modelData[1]
        color: Color.foreground
        font.family: Style.font.family
        font.pixelSize: Style.font.bodySmall
      }
      TextField {
        width: parent.width
        enabled: !root.busy
        password: modelData[2]
        selectByMouse: true
        text: root.edits[modelData[0]] !== undefined ? root.edits[modelData[0]] : (modelData[2] ? "" : root.saved[modelData[0]] || "")
        placeholderText: modelData[2] && root.saved[modelData[0]] ? "Saved · leave blank to keep" : modelData[1]
        onTextEdited: {
          const copy = Object.assign({}, root.edits)
          copy[modelData[0]] = text
          root.edits = copy
        }
      }
    }
  }
  Flow {
    width: parent.width
    spacing: Style.space(6)
    Button { text: "Save"; enabled: !root.busy; focusable: true; bordered: true; onClicked: root.requested("config-save", {values: Object.assign({}, root.edits)}) }
    Button {
      visible: root.platform === "spotify" || root.platform === "tidal"
      text: "Connect " + (root.platform === "spotify" ? "Spotify" : "Tidal")
      enabled: !root.busy
      focusable: true
      bordered: true
      onClicked: root.requested(root.platform + "-connect", {values: root.edits})
    }
    Button {
      text: "Forget this platform"
      enabled: !root.busy
      focusable: true
      onClicked: root.requested("config-forget", {platform: root.platform})
    }
  }
  Text {
    width: parent.width
    text: "Saved privately in ~/.config/yoink/settings.json. Secret fields stay hidden; blank fields preserve saved secrets."
    color: Color.foreground
    font.family: Style.font.family
    font.pixelSize: Style.font.bodySmall
    wrapMode: Text.Wrap
  }
}
