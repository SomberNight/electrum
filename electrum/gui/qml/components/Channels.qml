import QtQuick 2.6
import QtQuick.Layouts 1.0
import QtQuick.Controls 2.0
import QtQuick.Controls.Material 2.0

import org.electrum 1.0

import "controls"

Pane {
    property string title: qsTr("Lightning Channels")

    ColumnLayout {
        id: layout
        width: parent.width
        height: parent.height

        GridLayout {
            id: summaryLayout
            Layout.preferredWidth: parent.width
            columns: 2

            Label {
                Layout.columnSpan: 2
                text: ''
            }

            Label {
                text: qsTr('You can send:')
                color: Material.accentColor
            }

            Label {
                text: ''
            }

            Label {
                text: qsTr('You can receive:')
                color: Material.accentColor
            }

            Label {
                text: ''
            }

            RowLayout {
                Layout.columnSpan: 2

                Button {
                    text: qsTr('Open Channel')
                    onClicked: app.stack.push(Qt.resolvedUrl('OpenChannel.qml'))
                }
            }
        }


        Frame {
            id: channelsFrame
            Layout.preferredWidth: parent.width
            Layout.fillHeight: true
            verticalPadding: 0
            horizontalPadding: 0
            background: PaneInsetBackground {}

            ColumnLayout {
                spacing: 0
                anchors.fill: parent

                Item {
                    Layout.preferredHeight: hitem.height
                    Layout.preferredWidth: parent.width
                    Rectangle {
                        anchors.fill: parent
                        color: Qt.lighter(Material.background, 1.25)
                    }
                    RowLayout {
                        id: hitem
                        width: parent.width
                        Label {
                            text: qsTr('Channels')
                            font.pixelSize: constants.fontSizeLarge
                            color: Material.accentColor
                        }
                    }
                }

                ListView {
                    id: listview
                    Layout.preferredWidth: parent.width
                    Layout.fillHeight: true
                    clip: true
                    model: Daemon.currentWallet.channelModel

                    delegate: ChannelDelegate {
                        highlighted: ListView.isCurrentItem
                    }

                    ScrollIndicator.vertical: ScrollIndicator { }
                }
            }
        }

    }

    Component.onCompleted: Daemon.currentWallet.channelModel.init_model()
}