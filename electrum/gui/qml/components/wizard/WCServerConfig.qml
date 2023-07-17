import QtQuick
import QtQuick.Layouts
import QtQuick.Controls

import "../controls"

WizardComponent {
    valid: true
    last: true

    function apply() {
        wizard_data['autoconnect'] = sc.auto_connect
        wizard_data['server'] = sc.address
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: constants.paddingLarge

        Label {
            text: qsTr('Server settings')
        }

        ServerConfig {
            id: sc
            width: parent.width
            Layout.fillHeight: true
        }
    }
}
