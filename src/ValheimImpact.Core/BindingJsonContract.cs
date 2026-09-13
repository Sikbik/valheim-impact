using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Runtime.Serialization.Json;
using System.Xml;

namespace ValheimImpact.Core
{
    // Schema 3 checks the original JSON types before admitting deserialized values.
    // Legacy schema parsing remains unchanged; new semantics require version 3.
    internal static class BindingJsonContract
    {
        internal static void Validate(Stream stream)
        {
            var document = new XmlDocument();
            var quotas = new XmlDictionaryReaderQuotas { MaxDepth = 16, MaxArrayLength = 16384,
                MaxStringContentLength = 1048576, MaxNameTableCharCount = 16384, MaxBytesPerRead = 4096 };
            using (var reader = JsonReaderWriterFactory.CreateJsonReader(stream, quotas)) document.Load(reader);
            XmlElement root = document.DocumentElement;
            XmlElement schema = root["schemaVersion"];
            Fields(root, "schemaVersion", "bindings"); Integer(schema);
            XmlElement rules = root["bindings"];
            Require(rules.GetAttribute("type") == "array");
            foreach (XmlElement rule in rules.ChildNodes)
            {
                bool grass = rule["grass"] != null, cutout = rule["cutout"] != null;
                var fields = new List<string> { "id", "materialName", "shaderName", "textureProperty", "originalTextureName", "ownedTextureId", "originalWidth", "originalHeight" };
                if (grass) fields.Add("grass");
                if (cutout) fields.Add("cutout");
                Fields(rule, fields.ToArray()); Require(!(grass && cutout));
                foreach (string key in fields)
                {
                    if (key == "grass" || key == "cutout") continue;
                    if (key == "originalWidth" || key == "originalHeight") Integer(rule[key]);
                    else Require(rule[key].GetAttribute("type") == "string");
                }
                if (grass)
                {
                    XmlElement state = rule["grass"];
                    Fields(state, "fixedPasses", "cutoff", "renderQueue", "terrainTextureName", "terrainWidth", "terrainHeight", "terrainColorScale", "swayDistance", "pushDistance");
                    foreach (XmlElement value in state.ChildNodes)
                        if (value.Name == "fixedPasses" || value.Name == "terrainTextureName") Require(value.GetAttribute("type") == "string");
                        else if (value.Name == "renderQueue" || value.Name == "terrainWidth" || value.Name == "terrainHeight") Integer(value);
                        else Number(value);
                }
                if (cutout)
                {
                    XmlElement state = rule["cutout"];
                    Fields(state, "mode", "cutoff", "cull", "zWrite", "srcBlend", "dstBlend", "renderQueue", "alphaTest");
                    foreach (XmlElement value in state.ChildNodes)
                        if (value.Name == "alphaTest") Require(value.GetAttribute("type") == "boolean");
                        else if (value.Name == "renderQueue") Integer(value);
                        else Number(value);
                }
            }
        }
        private static void Fields(XmlElement value, params string[] fields)
        {
            Require(value != null && value.GetAttribute("type") == "object");
            var remaining = new HashSet<string>(fields, StringComparer.Ordinal);
            foreach (XmlElement child in value.ChildNodes) Require(remaining.Remove(child.Name));
            Require(remaining.Count == 0);
        }
        private static void Number(XmlElement value)
        {
            double parsed;
            Require(value.GetAttribute("type") == "number" && double.TryParse(value.InnerText, NumberStyles.Float, CultureInfo.InvariantCulture, out parsed) &&
                !double.IsNaN(parsed) && !double.IsInfinity(parsed));
        }
        private static void Integer(XmlElement value)
        {
            int parsed;
            Require(value.GetAttribute("type") == "number" && int.TryParse(value.InnerText, NumberStyles.AllowLeadingSign, CultureInfo.InvariantCulture, out parsed));
        }
        private static void Require(bool value) { if (!value) throw new InvalidDataException("Invalid schema 3 binding field or JSON type"); }
    }
}
