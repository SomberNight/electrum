import QtQuick
import QtQuick.Controls
import QtMultimedia

import org.electrum 1.0

Item {
    id: scanner

    property bool active: false
    property string url
    property string scanData
    property string hint

    property bool _pointsVisible

    signal found

    function restart() {
        still.source = ''
        _pointsVisible = false // TODO: delete old points
        scanner.active = true
    }

    VideoOutput {
        id: vo
        anchors.fill: parent

        fillMode: VideoOutput.PreserveAspectCrop

        Rectangle {
            width: parent.width
            height: (parent.height - parent.width) / 2
            visible: camera.cameraStatus == Camera.ActiveStatus
            anchors.top: parent.top
            color: Qt.rgba(0,0,0,0.5)
        }
        Rectangle {
            width: parent.width
            height: (parent.height - parent.width) / 2
            visible: camera.cameraStatus == Camera.ActiveStatus
            anchors.bottom: parent.bottom
            color: Qt.rgba(0,0,0,0.5)
        }
        InfoTextArea {
            visible: scanner.hint
            background.opacity: 0.5
            iconStyle: InfoTextArea.IconStyle.None
            anchors {
                top: parent.top
                topMargin: constants.paddingXLarge
                left: parent.left
                leftMargin: constants.paddingXXLarge
                right: parent.right
                rightMargin: constants.paddingXXLarge
            }
            text: scanner.hint
        }

        Connections {
            target: vo.videoSink
            function onVideoFrameChanged() {
                if (scanner.active) {
                    var scanning = qr.scanSink(vo.videoSink)
                    if (scanning)
                        vo.grabToImage(function(result) {
                            if (result.image !== undefined) {
                                scanner.url = result.url
                            }
                        })
                }
            }
        }
    }

    Image {
        id: still
        anchors.fill: vo
    }

    SequentialAnimation {
        id: foundAnimation
        PropertyAction { target: scanner; property: '_pointsVisible'; value: true}
        PauseAnimation { duration: 280 }
        PropertyAction { target: scanner; property: '_pointsVisible'; value: false}
        PauseAnimation { duration: 280 }
        PropertyAction { target: scanner; property: '_pointsVisible'; value: true}
        PauseAnimation { duration: 280 }
        PropertyAction { target: scanner; property: '_pointsVisible'; value: false}
        PauseAnimation { duration: 280 }
        PropertyAction { target: scanner; property: '_pointsVisible'; value: true}
        PauseAnimation { duration: 80 }
        PropertyAction { target: scanner; property: '_pointsVisible'; value: false}
        PauseAnimation { duration: 80 }
        PropertyAction { target: scanner; property: '_pointsVisible'; value: true}
        onFinished: found()
    }

    Component {
        id: r
        Rectangle {
            property int cx
            property int cy
            width: 15
            height: 15
            x: cx - width/2
            y: cy - height/2
            radius: 5
            visible: scanner._pointsVisible
        }
    }

    Connections {
        target: qr
        function onDataChanged() {
            console.log(qr.data)
            scanner.active = false
            scanner.scanData = qr.data
            still.source = scanner.url

            // TODO: transform of qr points to rootitem/screen space is wrong
            var sx = still.width/still.sourceSize.width
            var sy = still.height/still.sourceSize.height
            var sx = still.width/qr.size
            var sy = still.height/qr.size
            r.createObject(scanner, {cx: qr.points[0].x * sx, cy: qr.points[0].y * sy, color: 'yellow'})
            r.createObject(scanner, {cx: qr.points[1].x * sx, cy: qr.points[1].y * sy, color: 'yellow'})
            r.createObject(scanner, {cx: qr.points[2].x * sx, cy: qr.points[2].y * sy, color: 'yellow'})
            r.createObject(scanner, {cx: qr.points[3].x * sx, cy: qr.points[3].y * sy, color: 'yellow'})

            foundAnimation.start()
        }
    }

    MediaDevices {
        id: mediaDevices
    }

    Camera {
        id: camera
        cameraDevice: mediaDevices.defaultVideoInput
        active: scanner.active
        focusMode: Camera.FocusModeAutoNear
        customFocusPoint: Qt.point(0.5, 0.5)

        // function dumpstats() {
        //     var camformats = cameraDevice.videoFormats
        //     var selected = null
        //     camformats.forEach(function(item, i) {
        //         if (item.pixelFormat == 0)
        //             return
        //         console.log('fps=' + item.maxFrameRate + ', res=' + item.resolution)
        //         console.log('pf=' + item.pixelFormat)
        //         if (item.maxFrameRate == 30 && item.resolution.width==640 && (item.pixelFormat == 17 || item.pixelFormat == 15)) {
        //             console.log('selecting format')
        //             selected = item
        //         }
        //     })
        //     camera.cameraFormat = selected
        //
        //     // TODO
        //     // pick a suitable resolution from the available resolutions
        //     // problem: some cameras have no supportedViewfinderResolutions
        //     // but still error out when an invalid resolution is set.
        //     // 640x480 seems to be universally available, but this needs to
        //     // be checked across a range of phone models.
        // }
    }

    CaptureSession {
        videoOutput: vo
        camera: camera
    }

    QRParser {
        id: qr
    }

    Component.onCompleted: {
        // console.log('enumerating cameras')
        // var cam = null
        //
        // mediaDevices.videoInputs.forEach(function(item) {
        //     console.log('cam found, id=' + item.id + ' name=' + item.description)
        //     console.log('pos=' + item.position)
        //     if ((item.id == '0' || item.id == 'back')) { // && item.position == CameraDevice.BackFace) {
        //         console.log('selecting camera')
        //         cam = item
        //     }
        //
        // })
        // if (cam != null) {
        //     camera.cameraDevice = cam
        // }
        // camera.dumpstats()

        scanner.active = true
    }
}
