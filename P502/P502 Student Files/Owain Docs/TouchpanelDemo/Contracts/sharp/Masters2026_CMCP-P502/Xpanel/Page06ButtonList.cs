using CMCPP502;

namespace Masters2026.Xpanel
{
    /// <summary>
    /// Implements the Crestron Construct contracts for the page 6 controls.
    /// </summary>
    internal class Page06ButtonList
    {
        /// <summary>
        /// The contracts to be implemented within the page.
        /// </summary>
        private readonly Contract contract;

        /// <summary>
        /// The number of button in the button list.
        /// </summary>
        private ushort buttonCount = 20;

        /// <summary>
        /// Initializes a new instance of the <see cref="Page06ButtonList"/> class.
        /// </summary>
        /// <param name="contract">The contracts to implement with this control page.</param>
        internal Page06ButtonList(Contract contract)
        {
            this.contract = contract;
            this.SetUpButtonList(this.buttonCount);
            this.contract.Page06.ButtonList.Button_PressEvent += this.HandleButtonListPressEvent;

            this.contract.Page06.SetSize_LowerTouchEvent += this.HandleSetSizeLowerTouchEvent;
            this.contract.Page06.SetSize_LowerTouchfb(this.buttonCount);
        }

        /// <summary>
        /// Event handler for when a button in the list is pressed.
        /// </summary>
        /// <param name="sender">Where the event originated.</param>
        /// <param name="e">A <see cref="IndexedButtonEventArgs"/>.</param>
        private void HandleButtonListPressEvent(object sender, IndexedButtonEventArgs e)
        {
            EventViewer.AddEventToViewer("ButtonList", e);

            for (ushort i = 0; i <= this.buttonCount; i++)
            {
                this.contract.Page06.ButtonList.Button_Selected(i, i == e.ButtonIndex);
            }
        }

        /// <summary>
        /// Event handler for when a set size slider is adjusted.
        /// </summary>
        /// <param name="sender">Where the event originated.</param>
        /// <param name="e">A <see cref="UIEventArgs"/>.</param>
        private void HandleSetSizeLowerTouchEvent(object sender, UIEventArgs e)
        {
            EventViewer.AddEventToViewer("Set Size", e);

            this.SetUpButtonList(e.SigArgs.Sig.UShortValue);
            this.contract.Page06.SetSize_LowerTouchfb(e.SigArgs.Sig.UShortValue);
        }

        /// <summary>
        /// Sets up the button list to a new size.
        /// </summary>
        /// <param name="newButtonCount">The number of buttons you want in the list.</param>
        private void SetUpButtonList(ushort newButtonCount)
        {
            this.buttonCount = newButtonCount;
            this.contract.Page06.ButtonList.ButtonList_ListNumberOfItems(this.buttonCount);

            for (ushort i = 0; i < this.buttonCount; i++)
            {
                int indexLabel = i + 1;
                this.contract.Page06.ButtonList.Button_Text(i, $"Preset {indexLabel}");
            }
        }
    }
}
