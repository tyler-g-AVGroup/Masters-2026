using CMCPP502;

namespace Masters2026.Xpanel
{
    /// <summary>
    /// Implements the Crestron Construct contracts for the page 2 controls.
    /// </summary>
    internal class Page02Slider
    {
        /// <summary>
        /// The contracts to be implemented within the page.
        /// </summary>
        private readonly Contract contract;

        /// <summary>
        /// Initializes a new instance of the <see cref="Page02Slider"/> class.
        /// </summary>
        /// <param name="contract">The contracts to implement with this control page.</param>
        internal Page02Slider(Contract contract)
        {
            this.contract = contract;
            this.contract.Page02.Slider_LowerTouchEvent += this.HandleSliderLowerTouchEvent;
            this.contract.Page02.Preset25_PressEvent += this.HandlePreset25PressEvent;
            this.contract.Page02.Preset50_PressEvent += this.HandlePreset50PressEvent;
            this.contract.Page02.Preset75_PressEvent += this.HandlePreset75PressEvent;
        }

        /// <summary>
        /// Event handler for when the 25% preset button is pressed.
        /// </summary>
        /// <param name="sender">Where the event originated.</param>
        /// <param name="e">A <see cref="UIEventArgs"/>.</param>
        private void HandlePreset25PressEvent(object sender, UIEventArgs e)
        {
            EventViewer.AddEventToViewer("Preset25Button", e);

            if (e.SigArgs.Sig.BoolValue)
            {
                this.UpdatePresetFeedback(.25);
            }
        }

        /// <summary>
        /// Event handler for when the 50% preset button is pressed.
        /// </summary>
        /// <param name="sender">Where the event originated.</param>
        /// <param name="e">A <see cref="UIEventArgs"/>.</param>
        private void HandlePreset50PressEvent(object sender, UIEventArgs e)
        {
            EventViewer.AddEventToViewer("Preset50Button", e);

            if (e.SigArgs.Sig.BoolValue)
            {
                this.UpdatePresetFeedback(.5);
            }
        }

        /// <summary>
        /// Event handler for when the 75% preset button is pressed.
        /// </summary>
        /// <param name="sender">Where the event originated.</param>
        /// <param name="e">A <see cref="UIEventArgs"/>.</param>
        private void HandlePreset75PressEvent(object sender, UIEventArgs e)
        {
            EventViewer.AddEventToViewer("Preset75Button", e);

            if (e.SigArgs.Sig.BoolValue)
            {
                this.UpdatePresetFeedback(.75);
            }
        }

        /// <summary>
        /// Event handler for when the slider has been pressed.
        /// </summary>
        /// <param name="sender">Where the event originated.</param>
        /// <param name="e">A <see cref="UIEventArgs"/>.</param>
        private void HandleSliderLowerTouchEvent(object sender, UIEventArgs e)
        {
            EventViewer.AddEventToViewer("Slider", e);

            this.contract.Page02.Slider_LowerTouchfb(e.SigArgs.Sig.UShortValue);
        }

        /// <summary>
        /// Updates the slider feedback with the percentage provided.
        /// </summary>
        /// <param name="percentage">The percentage of the max slider value to be updated to.</param>
        private void UpdatePresetFeedback(double percentage)
        {
            this.contract.Page02.Slider_LowerTouchfb((ushort)(ushort.MaxValue * percentage));
        }
    }
}
