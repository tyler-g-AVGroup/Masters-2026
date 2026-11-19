using CMCPP502;
using Crestron.SimplSharpPro.DeviceSupport;
using Independentsoft.Exchange;

namespace Masters2026.Xpanel
{
    /// <summary>
    /// Implements Crestron Construct contracts against a panel.
    /// </summary>
    internal class DemoPanel
    {
        /// <summary>
        /// The contracts to be implemented for the provided panel.
        /// </summary>
        private readonly Contract contract;

        /// <summary>
        /// Initializes a new instance of the <see cref="DemoPanel"/> class.
        /// </summary>
        /// <param name="panel">The panel to implement the contracts.</param>
        internal DemoPanel(BasicTriListWithSmartObject panel)
        {
            this.contract = new Contract(panel);
            this.contract.
            new PageEventViewer(this.contract);
            this.contract.PageSelection.PageNavigation.Button_PressEvent += this.HandlePageNavigationButtonPressEvent;
            new Page01Button(this.contract);
            new Page02Slider(this.contract);
            new Page03Text(this.contract);
            new Page04Dpad(this.contract);
            new Page05KeypadPad(this.contract);
            new Page06ButtonList(this.contract);
            new Page07WidgetList(this.contract);
        }

        /// <summary>
        /// Event handler for when a main navigation button is pressed.
        /// </summary>
        /// <param name="sender">Where the event originated.</param>
        /// <param name="e">A <see cref="UIEventArgs"/>.</param>
        private void HandlePageNavigationButtonPressEvent(object sender, IndexedButtonEventArgs e)
        {
            EventViewer.AddEventToViewer("PageNavigation", e);

            this.contract.Page01.VisibilityJoin(e.ButtonIndex == 0);
            this.contract.Page02.VisibilityJoin(e.ButtonIndex == 1);
            this.contract.Page03.VisibilityJoin(e.ButtonIndex == 2);
            this.contract.Page04.VisibilityJoin(e.ButtonIndex == 3);
            this.contract.Page05.VisibilityJoin(e.ButtonIndex == 4);
            this.contract.Page06.VisibilityJoin(e.ButtonIndex == 5);
            this.contract.Page07.VisibilityJoin(e.ButtonIndex == 6);

            for (ushort i = 0; i < 8; i++)
            {
                this.contract.PageSelection.PageNavigation.Button_Selected(i, i == e.ButtonIndex);
            }
        }
    }
}
