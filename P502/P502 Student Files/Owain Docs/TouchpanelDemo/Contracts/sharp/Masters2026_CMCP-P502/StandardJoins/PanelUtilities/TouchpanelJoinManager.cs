using System;
using Crestron.SimplSharpPro.DeviceSupport;

namespace Masters2026.StandardJoins.PanelUtilities
{
    /// <summary>
    /// Helper methods for reacting to join presses on a touch panel.
    /// </summary>
    public static class TouchpanelJoinManager
    {
        /// <summary>
        /// Adds a boolean action to the specific join's UserObject that will be invoked when the join transitions to high.
        /// </summary>
        /// <param name = "panel" > The panel to associate the action with.</param>
        /// <param name = "join" > The join number to associate the action with.</param>
        /// <param name = "action" > The action to be executed when the join number is pressed.</param>
        public static void AddBooleanPress(this BasicTriList panel, uint join, Action action)
        {
            Action<bool> pressAction = (b) =>
            {
                if (b)
                {
                    action();
                }
            };

            panel.AddBooleanAction(join, pressAction);
        }

        /// <summary>
        /// Adds a boolean action to the specific smart object's join's UserObject that will be invoked when the join transitions to high.
        /// </summary>
        /// <param name = "panel" > The panel to associate the action with.</param>
        /// <param name = "smartGraphicsId" > The smart graphic ID to associate the action with.</param>
        /// <param name = "sigName" > The smart graphic signal name to associate the action with.</param>
        /// <param name = "action" > The action to be executed when the join number is pressed.</param>
        public static void AddBooleanPress(this BasicTriListWithSmartObject panel, uint smartGraphicsId, string sigName, Action action)
        {
            Action<bool> pressAction = (b) =>
            {
                if (b)
                {
                    action();
                }
            };

            panel.AddBooleanAction(smartGraphicsId, sigName, pressAction);
        }

        /// <summary>
        /// Adds a collection of boolean actions to the specific join's UserObject.
        /// </summary>
        /// <param name = "panel" > The panel to associate the action with.</param>
        /// <param name = "join" > The join number to associate the action with.</param>
        /// <param name = "action" > The actions to be executed when the join number is pressed.</param>
        public static void AddBooleanAction(this BasicTriList panel, uint join, Action<bool> action)
        {
            if (panel.BooleanOutput[join].UserObject is Action<bool> actions)
            {
                actions += action;
                panel.BooleanOutput[join].UserObject = actions;
            }
            else
            {
                panel.BooleanOutput[join].UserObject = action;
            }
        }

        /// <summary>
        /// Adds a collection of boolean actions to the smart object's join's UserObject.
        /// </summary>
        /// <param name = "panel" > The panel to associate the action with.</param>
        /// <param name = "smartGraphicsId" > The smart graphic ID to associate the action with.</param>
        /// <param name = "sigName" > The smart graphic signal name to associate the action with.</param>
        /// <param name = "action" > The action to be executed when the join number is pressed.</param>
        public static void AddBooleanAction(this BasicTriListWithSmartObject panel, uint smartGraphicsId, string sigName, Action<bool> action)
        {
            if (panel.SmartObjects[smartGraphicsId].BooleanOutput[sigName].UserObject is Action<bool> actions)
            {
                actions += action;
                panel.SmartObjects[smartGraphicsId].BooleanOutput[sigName].UserObject = actions;
            }
            else
            {
                panel.SmartObjects[smartGraphicsId].BooleanOutput[sigName].UserObject = action;
            }
        }
    }
}