package main

import (
	"fmt"
	"log"
	"os"

	"gopkg.in/yaml.v3"
)

type DeploymentImagePatch struct {
	APIVersion string `yaml:"apiVersion"`
	Kind       string `yaml:"kind"`
	Metadata   struct {
		Name      string `yaml:"name"`
	} `yaml:"metadata"`
	Spec struct {
		Replicas int `yaml:"replicas,omitempty"`
		Template struct {
			Spec struct {
				Containers []struct {
					Name  string `yaml:"name"`
					Image string `yaml:"image"`
				} `yaml:"containers"`
			} `yaml:"spec"`
		} `yaml:"template"`
	} `yaml:"spec"`
}

func main() {
	if len(os.Args) != 4 {
		panic("Invalid call")
	}

	environment := os.Args[1]
	app := os.Args[2]
	version := os.Args[3]

	log.Println("Upgrading", app, "in", environment, "to", version)
	filename := fmt.Sprintf(
		"../../apps/%s/%s/patch-deployment.yaml",
		environment,
		app,
	)

	// Read the file
	file, err := os.ReadFile(filename)
	if err != nil {
		panic("Error reading file")
	}

	var deployment DeploymentImagePatch
	if err := yaml.Unmarshal(file, &deployment); err != nil {
		log.Fatalf("Error unmarshalling: %v", err)
	}
	log.Println("Current deployment: ", deployment)

	// Update the version
	var newImage string
	if strings.HasPrefix(version, "sha256:") {
		newImage = fmt.Sprintf(
			"ghcr.io/profianinc/%s@%s",
			app,
			version,
		)
	} else {
		newImage := fmt.Sprintf(
			"ghcr.io/profianinc/%s:%s",
			app,
			version,
		)
	}
	deployment.Spec.Template.Spec.Containers[0].Image = newImage
	log.Println("Updated deployment: ", deployment)

	// Build the new YAML file
	newFilename := fmt.Sprintf("%s.new", filename)
	newF, err := os.Create(newFilename)
	if err != nil {
		log.Fatalf("Error creating new file: %v", err)
	}
	defer os.Remove(newF.Name())

	encoder := yaml.NewEncoder(newF)
	encoder.SetIndent(2)
	if err := encoder.Encode(deployment); err != nil {
		log.Fatalf("Error marshalling: %v", err)
	}
	if err := encoder.Close(); err != nil {
		log.Fatalf("Error closing: %v", err)
	}
	if err := newF.Close(); err != nil {
		log.Fatalf("Error closing: %v", err)
	}
	if err := os.Rename(newFilename, filename); err != nil {
		log.Fatalf("Error renaming: %v", err)
	}
	log.Println("Done")
}
