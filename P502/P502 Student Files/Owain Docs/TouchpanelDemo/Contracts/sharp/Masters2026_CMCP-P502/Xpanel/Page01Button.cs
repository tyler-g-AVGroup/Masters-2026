using CMCPP502;

namespace Masters2026.Xpanel
{
    /// <summary>
    /// Implements the Crestron Construct contracts for the page 1 controls.
    /// </summary>
    internal class Page01Button
    {
        /// <summary>
        /// The contracts to be implemented within the page.
        /// </summary>
        private readonly Contract contract;

        /// <summary>
        /// Whether the main button is enabled.
        /// </summary>
        private bool isButtonEnabled = true;

        /// <summary>
        /// Whether the main button is selected.
        /// </summary>
        private bool isButtonSelected;

        /// <summary>
        /// Whether the main button is visible.
        /// </summary>
        private bool isButtonVisible = true;

        /// <summary>
        /// Initializes a new instance of the <see cref="Page01Button"/> class.
        /// </summary>
        /// <param name="contract">The contracts to implement with this control page.</param>
        internal Page01Button(Contract contract)
        {
            this.contract = contract;
            this.contract.Page01.ButtonMain_PressEvent += this.HandlePage01ButtonMainPressEvent;
            this.contract.Page01.ButtonEnableToggle_PressEvent += this.HandlePage01ButtonEnableTogglePressEvent;
            this.contract.Page01.ButtonVisibilityToggle_PressEvent += this.HandlePage01ButtonVisibilityTogglePressEvent;
            this.contract.Page01.ButtonMain_Visibility_fb(this.isButtonVisible);
            this.contract.Page01.ButtonMain_Enable(this.isButtonEnabled);
            this.contract.Page01.ButtonMain_IndirectText("Mute");

            ////// This uses the overload of the ButtonMain_Enable method where a delegate is used to set the enable state of the button.
            // this.contract.Page01.ButtonMain_Enable((sig, page) =>
            // {
            //    sig.BoolValue = true;
            // });

            ////// This uses the overload of the ButtonMain_Selected method where a delegate is used to set the selected state of the button.
            // this.contract.Page01.ButtonMain_Selected((sig, page) =>
            // {
            //    sig.BoolValue = true;
            // });
        }

        /// <summary>
        /// Event handler for when the enable toggle button is pressed.
        /// </summary>
        /// <param name="sender">Where the event originated.</param>
        /// <param name="e">A <see cref="UIEventArgs"/>.</param>
        private void HandlePage01ButtonEnableTogglePressEvent(object sender, UIEventArgs e)
        {
            EventViewer.AddEventToViewer("ButtonEnable", e);

            if (e.SigArgs.Sig.BoolValue)
            {
                this.isButtonEnabled = !this.isButtonEnabled;
                this.contract.Page01.ButtonMain_Enable(this.isButtonEnabled);
            }
        }

        /// <summary>
        /// Event handler for when the main toggle button is pressed.
        /// </summary>
        /// <param name="sender">Where the event originated.</param>
        /// <param name="e">A <see cref="UIEventArgs"/>.</param>
        private void HandlePage01ButtonMainPressEvent(object sender, UIEventArgs e)
        {
            EventViewer.AddEventToViewer("ButtonMain", e);

            if (e.SigArgs.Sig.BoolValue)
            {
                this.isButtonSelected = !this.isButtonSelected;
                this.contract.Page01.ButtonMain_Selected(this.isButtonSelected);
                this.contract.Page01.ButtonMain_IndirectText(this.isButtonSelected ? "Muted" : "Mute");

                // This is the long version of the ternary expression above 'this.isButtonSelected ? "Muted" : "Mute"'
                // if (this.isButtonSelected)
                // {
                //    this.contract.Page01.ButtonMain_IndirectText("Muted");
                // }
                // else
                // {
                //    this.contract.Page01.ButtonMain_IndirectText("Mute");
                // }
            }
        }

        /// <summary>
        /// Event handler for when the visibility toggle button is pressed.
        /// </summary>
        /// <param name="sender">Where the event originated.</param>
        /// <param name="e">A <see cref="UIEventArgs"/>.</param>
        private void HandlePage01ButtonVisibilityTogglePressEvent(object sender, UIEventArgs e)
        {
            EventViewer.AddEventToViewer("ButtonVisibility", e);

            if (e.SigArgs.Sig.BoolValue)
            {
                this.isButtonVisible = !this.isButtonVisible;
                this.contract.Page01.ButtonMain_Visibility_fb(this.isButtonVisible);
            }
        }
    }
}
