import CoreGraphics
import Foundation

let stateURL = FileManager.default.homeDirectoryForCurrentUser
    .appendingPathComponent(".codex/.codex-global-state.json")
let data = try Data(contentsOf: stateURL)
let root = try JSONSerialization.jsonObject(with: data) as! [String: Any]
let overlay = root["electron-avatar-overlay-bounds"] as! [String: Any]
let anchor = overlay["anchor"] as! [String: Any]

let x = anchor["x"] as! CGFloat
let y = anchor["y"] as! CGFloat
let width = anchor["width"] as! CGFloat
let height = anchor["height"] as! CGFloat
let center = CGPoint(x: x + width / 2, y: y + height / 2)
let outside = CGPoint(x: x - 40, y: y - 40)
let original = CGEvent(source: nil)!.location

guard !CGEventSource.buttonState(.combinedSessionState, button: .left) else {
    fputs("Left mouse button is pressed; probe cancelled.\n", stderr)
    exit(2)
}

func move(to point: CGPoint) {
    let event = CGEvent(
        mouseEventSource: nil,
        mouseType: .mouseMoved,
        mouseCursorPosition: point,
        mouseButton: .left
    )!
    event.post(tap: .cghidEventTap)
}

defer { move(to: original) }
move(to: outside)
Thread.sleep(forTimeInterval: 0.5)
move(to: center)
Thread.sleep(forTimeInterval: 1.9)
move(to: outside)
Thread.sleep(forTimeInterval: 0.5)
move(to: center)
Thread.sleep(forTimeInterval: 1.9)
move(to: outside)
Thread.sleep(forTimeInterval: 0.5)
